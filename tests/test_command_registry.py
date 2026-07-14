"""Command extension contract tests.

Spec references:
- docs/specs/02-taut-core.md [TAUT-8.1], [TAUT-8.3], [TAUT-8.6]
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.sqlite_only


def test_installed_fixture_declares_command_protocol_core_floor() -> None:
    fixture_manifest = (
        Path(__file__).parent / "fixtures" / "taut_command_plugin" / "pyproject.toml"
    )
    with fixture_manifest.open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["dependencies"] == ["taut>=0.6.0"]


class _EchoCommand:
    def configure_parser(self, parser: Any) -> None:
        parser.add_argument("value")

    def run(self, context: Any, args: argparse.Namespace) -> int:
        context.stdout.write(
            f"{args.value}|{context.db_path}|{context.as_name}|"
            f"{context.auth_token}|{context.json}|{context.timestamps}|"
            f"{context.quiet}\n"
        )
        return 0


def _create_echo_command() -> _EchoCommand:
    return _EchoCommand()


class _NamespaceCommand:
    def configure_parser(self, parser: Any) -> None:
        parser.add_argument("value")

    def run(self, context: Any, args: argparse.Namespace) -> int:
        fields = ",".join(sorted(vars(args)))
        context.stdout.write(f"{str(context.quiet).lower()}|{fields}\n")
        return 0


def _create_namespace_command() -> _NamespaceCommand:
    return _NamespaceCommand()


class _LocalOptionCommand:
    def configure_parser(self, parser: Any) -> None:
        parser.add_argument("--persona")

    def run(self, context: Any, args: argparse.Namespace) -> int:
        context.stdout.write(f"{args.persona}\n")
        return 0


def _create_local_option_command() -> _LocalOptionCommand:
    return _LocalOptionCommand()


class _InvalidReturnCommand(_EchoCommand):
    def run(self, context: Any, args: argparse.Namespace) -> int:
        return 7


def _create_invalid_return_command() -> _InvalidReturnCommand:
    return _InvalidReturnCommand()


class _BooleanReturnCommand(_EchoCommand):
    def run(self, context: Any, args: argparse.Namespace) -> int:
        return True


def _create_boolean_return_command() -> _BooleanReturnCommand:
    return _BooleanReturnCommand()


class _CommandErrorCommand:
    def configure_parser(self, parser: Any) -> None:
        pass

    def run(self, context: Any, args: argparse.Namespace) -> int:
        from taut.commands import CommandError

        raise CommandError("nothing matched", exit_code=2)


def _create_command_error_command() -> _CommandErrorCommand:
    return _CommandErrorCommand()


class _ControlErrorCommand:
    def configure_parser(self, parser: Any) -> None:
        pass

    def run(self, context: Any, args: argparse.Namespace) -> int:
        from taut.commands import CommandError

        raise CommandError("failed\x1b]0;title\x07\x9b\r\b\t\nrow")


def _create_control_error_command() -> _ControlErrorCommand:
    return _ControlErrorCommand()


class _UnexpectedBaseException(BaseException):
    pass


class _BaseExceptionCommand:
    def configure_parser(self, parser: Any) -> None:
        pass

    def run(self, context: Any, args: argparse.Namespace) -> int:
        raise _UnexpectedBaseException("base exploded")


def _create_base_exception_command() -> _BaseExceptionCommand:
    return _BaseExceptionCommand()


class _ConfigureFailureCommand:
    def configure_parser(self, parser: Any) -> None:
        raise RuntimeError("configure exploded")

    def run(self, context: Any, args: argparse.Namespace) -> int:
        return 0


def _create_configure_failure_command() -> _ConfigureFailureCommand:
    return _ConfigureFailureCommand()


def _factory_requires_argument(required: object) -> _EchoCommand:
    return _EchoCommand()


def _factory_returns_object() -> object:
    return object()


def _factory_raises_system_exit() -> object:
    raise SystemExit(17)


class _ConfigureSystemExitCommand:
    def configure_parser(self, parser: Any) -> None:
        raise SystemExit(18)

    def run(self, context: Any, args: argparse.Namespace) -> int:
        return 0


def _create_configure_system_exit_command() -> _ConfigureSystemExitCommand:
    return _ConfigureSystemExitCommand()


class _RunSystemExitCommand:
    def configure_parser(self, parser: Any) -> None:
        pass

    def run(self, context: Any, args: argparse.Namespace) -> int:
        raise SystemExit(19)


def _create_run_system_exit_command() -> _RunSystemExitCommand:
    return _RunSystemExitCommand()


def _raise_parse_system_exit(value: str) -> str:
    raise SystemExit(None if value == "none" else value)


class _ParseSystemExitCommand:
    def configure_parser(self, parser: Any) -> None:
        parser.add_argument("value", type=_raise_parse_system_exit)

    def run(self, context: Any, args: argparse.Namespace) -> int:
        return 0


def _create_parse_system_exit_command() -> _ParseSystemExitCommand:
    return _ParseSystemExitCommand()


class _ClientCommand:
    def configure_parser(self, parser: Any) -> None:
        pass

    def run(self, context: Any, args: argparse.Namespace) -> int:
        context.stdout.write(str(context.client() is context.client()).lower() + "\n")
        return 0


def _create_client_command() -> _ClientCommand:
    return _ClientCommand()


class _FailingClientCommand(_ClientCommand):
    def run(self, context: Any, args: argparse.Namespace) -> int:
        context.client()
        raise RuntimeError("primary command failure")


def _create_failing_client_command() -> _FailingClientCommand:
    return _FailingClientCommand()


class _DisposableClient:
    def __init__(self, *, close_error: bool = False) -> None:
        self.closed = False
        self.close_error = close_error

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            raise RuntimeError("cleanup failure")


@dataclass(frozen=True)
class _Distribution:
    name: str
    version: str = "1.0.0"

    @property
    def metadata(self) -> dict[str, str]:
        return {"Name": self.name}


@dataclass(frozen=True)
class _BrokenDistribution:
    broken_field: str
    name: str = "broken-provenance-owner"

    @property
    def metadata(self) -> dict[str, str]:
        if self.broken_field == "metadata":
            raise TypeError("distribution metadata exploded")
        return {"Name": self.name}

    @property
    def version(self) -> str:
        if self.broken_field == "version":
            raise TypeError("distribution version exploded")
        return "1.0.0"


@dataclass(frozen=True)
class _EntryPoint:
    name: str
    value: str
    loaded: Any
    distribution: Any | None = None
    group: str = "taut.commands"

    @property
    def dist(self) -> Any | None:
        return self.distribution

    def load(self) -> Any:
        if isinstance(self.loaded, BaseException):
            raise self.loaded
        return self.loaded


def test_command_author_surface_is_public() -> None:
    from taut.commands import (
        Command,
        CommandArgumentParser,
        CommandContext,
        CommandError,
        CommandFactory,
        CommandSpec,
        GlobalOption,
    )

    assert Command is not None
    assert CommandArgumentParser is not None
    assert CommandContext is not None
    assert CommandError is not None
    assert CommandFactory is not None
    assert CommandSpec is not None
    assert {option.name for option in GlobalOption} == {
        "DB",
        "AS",
        "TOKEN",
        "JSON",
        "TIMESTAMPS",
        "QUIET",
    }


def test_command_parser_intermixed_mode_is_explicit_and_preserves_trailing_positionals() -> (
    None
):
    from taut.commands import CommandArgumentParser

    intermixed = CommandArgumentParser(prog="intermixed")
    intermixed.enable_intermixed_args()
    intermixed.add_argument("name")
    intermixed.add_argument("threads", nargs="*")
    intermixed.add_argument("--provider")

    parsed = intermixed.parse_command_args(
        ["reviewer", "--provider", "scripted", "dev"]
    )

    assert parsed.name == "reviewer"
    assert parsed.provider == "scripted"
    assert parsed.threads == ["dev"]

    literal = intermixed.parse_command_args(["--", "-q"])

    assert literal.name == "-q"
    assert literal.threads == []


def test_static_builtins_do_not_depend_on_installed_metadata() -> None:
    from taut.commands._registry import CommandRegistry

    registry = CommandRegistry(entry_points=())

    assert registry.names() == (
        "init",
        "join",
        "leave",
        "set",
        "say",
        "reply",
        "read",
        "inbox",
        "log",
        "list",
        "watch",
        "rename",
        "who",
        "whoami",
        "rejoin",
        "summon",
        "dismiss",
    )


def test_reserved_summon_slots_are_static_compatibility_manifests() -> None:
    from taut.commands import GlobalOption
    from taut.commands._registry import CommandRegistry

    registry = CommandRegistry(entry_points=())

    summon = registry.get("summon")
    dismiss = registry.get("dismiss")
    assert summon.builtin is False
    assert dismiss.builtin is False
    assert summon.spec is not None
    assert dismiss.spec is not None
    assert summon.spec.post_verb_globals == frozenset({GlobalOption.DB})
    assert dismiss.spec.post_verb_globals == frozenset({GlobalOption.DB})
    assert summon.spec.implementation == (
        "taut.commands._summon_compat:create_summon_command"
    )
    assert dismiss.spec.implementation == (
        "taut.commands._summon_compat:create_dismiss_command"
    )


def test_unofficial_claim_cannot_override_reserved_summon_slot() -> None:
    from taut.commands import CommandSpec
    from taut.commands._registry import CommandRegistry

    claim = CommandSpec(
        1,
        "summon",
        "Counterfeit summon.",
        frozenset(),
        "counterfeit.command:create",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "summon",
                "counterfeit.manifest:summon",
                claim,
                _Distribution("counterfeit-owner"),
            ),
        )
    )

    assert registry.get("summon").spec is not None
    assert registry.get("summon").verbatim_tail is True
    assert registry.diagnostics() == (
        "installed command 'summon' from counterfeit-owner 1.0.0 "
        "(counterfeit.manifest:summon) cannot own the reserved first-party slot; "
        "the official owner is taut-summon",
    )


@pytest.mark.parametrize(
    ("name", "distribution_name"),
    [
        ("summon", "taut-summon"),
        ("dismiss", "taut_summon"),
        ("summon", "TAUT.SUMMON"),
    ],
)
def test_unique_normalized_official_claim_owns_reserved_slot(
    name: str,
    distribution_name: str,
) -> None:
    from taut.commands import CommandSpec
    from taut.commands._registry import CommandRegistry

    claim = CommandSpec(
        1,
        name,
        f"Official {name}.",
        frozenset(),
        f"official.command:create_{name}",
    )
    entry_point = _EntryPoint(
        name,
        f"official.manifest:{name}",
        claim,
        _Distribution(distribution_name),
    )

    selected = CommandRegistry(entry_points=(entry_point,)).get(name)

    assert selected.spec is claim
    assert selected.entry_point is entry_point
    assert selected.distribution_name == distribution_name
    assert selected.verbatim_tail is False
    assert selected.error is None


def test_actual_summon_manifests_own_both_reserved_slots_with_provenance() -> None:
    from taut_summon.command_manifest import dismiss, summon

    from taut.commands._registry import CommandRegistry

    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "dismiss",
                "taut_summon.command_manifest:dismiss",
                dismiss,
                _Distribution("taut-summon"),
            ),
            _EntryPoint(
                "summon",
                "taut_summon.command_manifest:summon",
                summon,
                _Distribution("taut-summon"),
            ),
        )
    )

    for name, expected in (("summon", summon), ("dismiss", dismiss)):
        selected = registry.get(name)
        assert selected.spec is expected
        assert selected.distribution_name == "taut-summon"
        assert selected.distribution_version == "1.0.0"
        assert selected.verbatim_tail is False
        assert selected.error is None


def test_official_claim_wins_reserved_slot_with_unofficial_diagnostic() -> None:
    from taut.commands import CommandSpec
    from taut.commands._registry import CommandRegistry

    official = CommandSpec(
        1,
        "summon",
        "Official summon.",
        frozenset(),
        "official.command:create_summon",
    )
    counterfeit = CommandSpec(
        1,
        "summon",
        "Counterfeit summon.",
        frozenset(),
        "counterfeit.command:create_summon",
    )
    entries = (
        _EntryPoint(
            "summon",
            "counterfeit.manifest:summon",
            counterfeit,
            _Distribution("counterfeit-owner"),
        ),
        _EntryPoint(
            "summon",
            "official.manifest:summon",
            official,
            _Distribution("taut-summon"),
        ),
    )

    forward = CommandRegistry(entry_points=entries)
    reverse = CommandRegistry(entry_points=reversed(entries))

    assert forward.get("summon").spec is official
    assert reverse.get("summon").spec is official
    assert (
        forward.diagnostics()
        == reverse.diagnostics()
        == (
            "installed command 'summon' from counterfeit-owner 1.0.0 "
            "(counterfeit.manifest:summon) cannot own the reserved first-party slot; "
            "the official owner is taut-summon",
        )
    )


def test_broken_official_claim_makes_reserved_slot_unavailable_without_fallback() -> (
    None
):
    from taut.commands._registry import CommandRegistry

    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "summon",
                "broken.manifest:summon",
                RuntimeError("official manifest exploded"),
                _Distribution("taut-summon"),
            ),
        )
    )

    selected = registry.get("summon")
    assert selected.spec is None
    assert selected.verbatim_tail is False
    assert selected.error is not None
    assert "taut-summon 1.0.0" in selected.error
    assert "official manifest exploded" in selected.error


def test_duplicate_official_claims_make_reserved_slot_unavailable() -> None:
    from taut.commands import CommandSpec
    from taut.commands._registry import CommandRegistry

    claim = CommandSpec(
        1,
        "summon",
        "Official summon.",
        frozenset(),
        "official.command:create_summon",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "summon",
                "official.manifest:first",
                claim,
                _Distribution("taut-summon"),
            ),
            _EntryPoint(
                "summon",
                "official.manifest:second",
                claim,
                _Distribution("taut_summon"),
            ),
        )
    )

    selected = registry.get("summon")
    assert selected.spec is None
    assert selected.verbatim_tail is False
    assert selected.error is not None
    assert "multiple official taut-summon entry points claim it" in selected.error
    assert "official.manifest:first" in selected.error
    assert "official.manifest:second" in selected.error
    assert registry.get("dismiss").verbatim_tail is True
    assert registry.get("init").spec is not None


def test_incompatible_official_claim_never_falls_back_to_legacy() -> None:
    from taut.commands import CommandSpec
    from taut.commands._registry import CommandRegistry

    incompatible = CommandSpec(
        2,
        "summon",
        "Future summon.",
        frozenset(),
        "official.command:create_summon",
    )
    selected = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "summon",
                "official.manifest:summon",
                incompatible,
                _Distribution("taut-summon"),
            ),
        )
    ).get("summon")

    assert selected.spec is None
    assert selected.verbatim_tail is False
    assert selected.error is not None
    assert "unsupported command interface version 2" in selected.error


def test_reserved_slots_are_selected_independently() -> None:
    from taut.commands import CommandSpec
    from taut.commands._registry import CommandRegistry

    official = CommandSpec(
        1,
        "summon",
        "Official summon.",
        frozenset(),
        "official.command:create_summon",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "summon",
                "official.manifest:summon",
                official,
                _Distribution("taut-summon"),
            ),
        )
    )

    assert registry.get("summon").spec is official
    assert registry.get("summon").verbatim_tail is False
    assert registry.get("dismiss").spec is not None
    assert registry.get("dismiss").verbatim_tail is True


def test_root_help_lists_broken_official_slot_once() -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "summon",
                "broken.manifest:summon",
                RuntimeError("official manifest exploded"),
                _Distribution("taut-summon"),
            ),
        )
    )
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["--help"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "summon       unavailable" in stdout.getvalue()
    assert "dismiss      Delegate agent-harness shutdown" in stdout.getvalue()
    assert stderr.getvalue().count("official manifest exploded") == 1


@pytest.mark.parametrize(
    ("argv", "expected_exit", "expected_stream", "expected_text"),
    [
        (
            ("summon", "reviewer", "--provider", "zz-unknown", "dev"),
            1,
            "stderr",
            "no adapter named 'zz-unknown'",
        ),
        (
            ("summon", "--help"),
            0,
            "stdout",
            "usage: taut-summon run",
        ),
        (
            ("summon", "--", "anything"),
            1,
            "stderr",
            "no adapter named 'anything'",
        ),
    ],
)
def test_reserved_summon_bridge_preserves_opaque_tail_and_exit_class(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: tuple[str, ...],
    expected_exit: int,
    expected_stream: str,
    expected_text: str,
) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    monkeypatch.chdir(tmp_path)
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        argv,
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == expected_exit
    selected_stream = stdout if expected_stream == "stdout" else stderr
    other_stream = stderr if expected_stream == "stdout" else stdout
    assert expected_text in selected_stream.getvalue()
    assert other_stream.getvalue() == ""


@pytest.mark.parametrize("db_position", ["before", "after"])
def test_reserved_summon_bridge_forwards_merged_database_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    db_position: str,
) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    monkeypatch.chdir(tmp_path)
    db_path = str(tmp_path / "chat.db")
    argv = (
        ["--db", db_path, "summon", "zz-unknown"]
        if db_position == "before"
        else ["summon", "zz-unknown", "--db", db_path]
    )
    stderr = StringIO()

    result = dispatch(
        argv,
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 1
    assert "no adapter named 'zz-unknown'" in stderr.getvalue()
    assert f"db: {db_path}" in stderr.getvalue()


def test_reserved_summon_bridge_uses_injected_stream_for_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.commands import _summon_compat
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    monkeypatch.setattr(_summon_compat.importlib.util, "find_spec", lambda _name: None)
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["summon", "claude"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (
        "taut summon requires the taut-summon extension "
        "(pipx inject taut taut-summon)\n"
    )


def test_reserved_summon_bridge_fails_loud_without_dispatch_separator() -> None:
    from taut.commands import CommandContext
    from taut.commands._summon_compat import create_summon_command

    context = CommandContext(
        db_path=None,
        as_name=None,
        auth_token=None,
        json=False,
        timestamps=False,
        quiet=False,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    with pytest.raises(
        RuntimeError,
        match="summon compatibility tail separator is missing",
    ):
        create_summon_command().run(context, argparse.Namespace(rest=[]))


def test_reserved_summon_bridge_line_buffers_and_escapes_legacy_python_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut_summon.cli

    from taut.commands import CommandContext
    from taut.commands._summon_compat import create_summon_command

    def legacy_main(_argv: list[str]) -> int:
        sys.stdout.write("first\x1b]52;c;Y2xpcGJvYXJk\x07")
        sys.stdout.write(" tail\nsecond\x9b[31m")
        sys.stderr.write("warning\r\b\t")
        return 0

    monkeypatch.setattr(taut_summon.cli, "main", legacy_main)
    stdout = StringIO()
    stderr = StringIO()
    context = CommandContext(
        db_path=None,
        as_name=None,
        auth_token=None,
        json=False,
        timestamps=False,
        quiet=False,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    result = create_summon_command().run(
        context,
        argparse.Namespace(rest=["--", "provider"]),
    )

    assert result == 0
    assert stdout.getvalue() == (
        r"first\x1b]52;c;Y2xpcGJvYXJk\a tail"
        "\n"
        r"second\x9b[31m"
        "\n"
    )
    assert stderr.getvalue() == r"warning\r\b\t" + "\n"


def test_compatible_installed_manifest_is_discovered_after_builtins() -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        command_api_version=1,
        name="fixture",
        summary="Fixture command.",
        post_verb_globals=frozenset({GlobalOption.DB}),
        implementation="fixture_package.command:create_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                name="fixture",
                value="fixture_package.manifest:fixture",
                loaded=manifest,
                distribution=_Distribution("Fixture.Package"),
            ),
        )
    )

    assert registry.names()[-1] == "fixture"
    selected = registry.get("fixture")
    assert selected.spec == manifest
    assert selected.distribution_name == "Fixture.Package"
    assert selected.distribution_version == "1.0.0"


@pytest.mark.parametrize(
    ("loaded", "message"),
    [
        (RuntimeError("manifest exploded"), "manifest exploded"),
        (SystemExit(17), "SystemExit(17)"),
        (object(), "must load a CommandSpec"),
        (
            pytest.param(
                "wrong-name",
                "does not match entry point",
                id="wrong-manifest-name",
            )
        ),
        (pytest.param("wrong-version", "unsupported command interface", id="version")),
        (pytest.param("empty-summary", "summary must be non-empty", id="summary")),
        (pytest.param("bad-target", "module:attribute", id="implementation")),
    ],
)
def test_bad_manifest_isolated_as_selected_command_error(
    loaded: object,
    message: str,
) -> None:
    from taut.commands import CommandSpec
    from taut.commands._registry import CommandRegistry

    if loaded == "wrong-name":
        loaded = CommandSpec(1, "other", "Other.", frozenset(), "pkg.cmd:create")
    elif loaded == "wrong-version":
        loaded = CommandSpec(2, "fixture", "Fixture.", frozenset(), "pkg.cmd:create")
    elif loaded == "empty-summary":
        loaded = CommandSpec(1, "fixture", "  ", frozenset(), "pkg.cmd:create")
    elif loaded == "bad-target":
        loaded = CommandSpec(1, "fixture", "Fixture.", frozenset(), "not-a-target")

    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                name="fixture",
                value="fixture_package.manifest:fixture",
                loaded=loaded,
                distribution=_Distribution("broken-fixture"),
            ),
        )
    )

    assert registry.get("init").spec is not None
    selected = registry.get("fixture")
    assert selected.spec is None
    assert selected.error is not None
    assert message in selected.error
    assert "broken-fixture 1.0.0" in selected.error


def test_conflicts_are_deterministic_and_cannot_override_builtins() -> None:
    from taut.commands import CommandSpec
    from taut.commands._registry import CommandRegistry

    external = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "fixture.command:create",
    )
    builtin_claim = CommandSpec(
        1,
        "say",
        "Counterfeit say.",
        frozenset(),
        "counterfeit.command:create",
    )
    entries = (
        _EntryPoint(
            "fixture",
            "zeta.manifest:fixture",
            external,
            _Distribution("zeta-owner"),
        ),
        _EntryPoint(
            "fixture",
            "alpha.manifest:fixture",
            external,
            _Distribution("alpha-owner"),
        ),
        _EntryPoint(
            "say",
            "counterfeit.manifest:say",
            builtin_claim,
            _Distribution("counterfeit"),
        ),
    )

    forward = CommandRegistry(entry_points=entries)
    reverse = CommandRegistry(entry_points=reversed(entries))

    assert forward.get("say").builtin is True
    assert reverse.get("say").builtin is True
    assert forward.get("fixture").spec is None
    assert forward.get("fixture").error == reverse.get("fixture").error
    assert forward.get("fixture").error == (
        "command 'fixture' is unavailable because multiple distributions claim it: "
        "alpha-owner 1.0.0 (alpha.manifest:fixture), "
        "zeta-owner 1.0.0 (zeta.manifest:fixture)"
    )


def test_dispatch_loads_and_runs_only_the_selected_adapter() -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(GlobalOption),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [
            "--db",
            "before.db",
            "--json",
            "fixture",
            "hello",
            "--db=after.db",
            "-t",
        ],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert stdout.getvalue() == "hello|after.db|None|None|True|True|False\n"
    assert stderr.getvalue() == ""


@pytest.mark.parametrize(
    "help_option",
    ["-h", "-qh", "-th", "--help", "--he"],
)
def test_root_help_accepts_released_spellings_and_unique_abbreviation(
    help_option: str,
) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [help_option],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert stdout.getvalue().startswith("usage: taut ")
    assert stderr.getvalue() == ""


def test_root_option_vocabulary_stays_aligned_with_help_and_global_enum() -> None:
    from taut.commands import GlobalOption
    from taut.commands._dispatch import _ROOT_LONG_OPTIONS, dispatch
    from taut.commands._registry import CommandRegistry

    expected = {
        "--help",
        "--version",
        *(f"--{option.value}" for option in GlobalOption),
    }
    assert set(_ROOT_LONG_OPTIONS) == expected

    stdout = StringIO()
    result = dispatch(
        ["--help"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert result == 0
    for spelling in expected:
        assert spelling in stdout.getvalue()


@pytest.mark.parametrize("version_option", ["--version", "--ver"])
def test_root_version_accepts_exact_and_unique_abbreviation(
    version_option: str,
) -> None:
    from taut.commands._dispatch import dispatch

    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [version_option],
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert stdout.getvalue().startswith("taut ")
    assert stderr.getvalue() == ""


@pytest.mark.parametrize(
    ("root_tokens", "expected"),
    [
        (("--timest",), "hello|None|None|None|False|True|False\n"),
        (("--tok", "secret"), "hello|None|None|secret|False|False|False\n"),
        (("--d=chat.db",), "hello|chat.db|None|None|False|False|False\n"),
        (("-tq",), "hello|None|None|None|False|True|True\n"),
        (("-qt",), "hello|None|None|None|False|True|True\n"),
    ],
)
def test_pre_verb_globals_keep_unambiguous_long_abbreviations(
    root_tokens: tuple[str, ...],
    expected: str,
) -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(GlobalOption),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [*root_tokens, "fixture", "hello"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0, stderr.getvalue()
    assert stdout.getvalue() == expected


def test_ambiguous_pre_verb_long_abbreviation_is_a_root_usage_error() -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["--t", "value", "whoami"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""
    assert "ambiguous option: --t" in stderr.getvalue()
    assert "--timestamps" in stderr.getvalue()
    assert "--token" in stderr.getvalue()


def test_repeated_exact_value_globals_use_textual_last_value() -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(GlobalOption),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()

    result = dispatch(
        [
            "--db",
            "first.db",
            "fixture",
            "hello",
            "--db",
            "second.db",
            "--db=third.db",
        ],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert result == 0
    assert stdout.getvalue().split("|")[1] == "third.db"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("--",), "usage: taut"),
        (("--wat", "whoami"), "unrecognized root option: --wat"),
        (("nosuchverb",), "unknown command: nosuchverb"),
        (("--db",), "argument --db: expected one value"),
    ],
)
def test_root_usage_failures_route_to_stderr_without_traceback(
    argv: tuple[str, ...],
    message: str,
) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        argv,
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""
    assert message in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["--db", "value.db"], "hello|value.db|None|None|False|False|False\n"),
        (["--db=value.db"], "hello|value.db|None|None|False|False|False\n"),
        (["--as", "Ada"], "hello|None|Ada|None|False|False|False\n"),
        (["--as=Ada"], "hello|None|Ada|None|False|False|False\n"),
        (["--token", "secret"], "hello|None|None|secret|False|False|False\n"),
        (["--token=secret"], "hello|None|None|secret|False|False|False\n"),
        (["--json"], "hello|None|None|None|True|False|False\n"),
        (["-t"], "hello|None|None|None|False|True|False\n"),
        (["--timestamps"], "hello|None|None|None|False|True|False\n"),
        (["-q"], "hello|None|None|None|False|False|True\n"),
        (["--quiet"], "hello|None|None|None|False|False|True\n"),
    ],
)
def test_declared_post_verb_globals_cover_every_spelling(
    tokens: list[str],
    expected: str,
) -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(GlobalOption),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()

    result = dispatch(
        ["fixture", "hello", *tokens],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert result == 0
    assert stdout.getvalue() == expected


def test_post_verb_declared_global_abbreviation_is_rejected() -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset({GlobalOption.QUIET}),
        "tests.test_command_registry:_create_namespace_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["fixture", "value", "--quie"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""
    assert "unrecognized arguments: --quie" in stderr.getvalue()


def test_exact_post_verb_global_is_removed_from_command_namespace() -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset({GlobalOption.QUIET}),
        "tests.test_command_registry:_create_namespace_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()

    result = dispatch(
        ["fixture", "value", "--quiet"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert result == 0
    assert stdout.getvalue() == "true|value\n"


def test_command_local_long_option_abbreviation_remains_available() -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset({GlobalOption.QUIET}),
        "tests.test_command_registry:_create_local_option_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["fixture", "--pers", "builder"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0, stderr.getvalue()
    assert stdout.getvalue() == "builder\n"


@pytest.mark.parametrize("option", ["--db", "--as", "--token"])
@pytest.mark.parametrize("next_token", ["--", "--json"])
@pytest.mark.parametrize("before_verb", [False, True])
def test_separated_global_value_does_not_swallow_option_or_separator(
    option: str,
    next_token: str,
    before_verb: bool,
) -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(GlobalOption),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    argv = (
        [option, next_token, "fixture", "value"]
        if before_verb
        else ["fixture", "value", option, next_token]
    )
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        argv,
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""
    assert f"argument {option}: expected one value" in stderr.getvalue()


@pytest.mark.parametrize(
    ("tokens", "expected_db"),
    [
        (("--db", "-1"), "-1"),
        (("--db", "-.5"), "-.5"),
        (("--db", "-"), "-"),
        (("--db=--option-like-path",), "--option-like-path"),
    ],
)
def test_global_values_preserve_argparse_negative_and_joined_forms(
    tokens: tuple[str, ...],
    expected_db: str,
) -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(GlobalOption),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()

    result = dispatch(
        ["fixture", "value", *tokens],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert result == 0
    assert stdout.getvalue().split("|")[1] == expected_db


@pytest.mark.parametrize("separator_before_verb", [False, True])
def test_literal_separator_keeps_option_like_tail_command_local(
    separator_before_verb: bool,
) -> None:
    from taut.commands import CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(GlobalOption),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    argv = (
        ["--", "fixture", "--db=literal"]
        if separator_before_verb
        else ["fixture", "--", "--db=literal"]
    )
    stdout = StringIO()

    result = dispatch(
        argv,
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert result == 0
    assert stdout.getvalue() == ("--db=literal|None|None|None|False|False|False\n")


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("missing_fixture_module:create", "No module named"),
        (
            "tests.test_command_registry:_factory_requires_argument",
            "callable with no arguments",
        ),
        (
            "tests.test_command_registry:_factory_returns_object",
            "did not return a command adapter",
        ),
        (
            "tests.test_command_registry:_create_configure_failure_command",
            "configure exploded",
        ),
        (
            "tests.test_command_registry:_create_invalid_return_command",
            "invalid exit value 7",
        ),
        (
            "tests.test_command_registry:_create_boolean_return_command",
            "invalid exit value True",
        ),
    ],
)
def test_selected_implementation_failures_are_concise(
    target: str,
    message: str,
) -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(1, "fixture", "Fixture.", frozenset(), target)
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stderr = StringIO()

    result = dispatch(
        ["fixture", "value"],
        registry=registry,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 1
    assert message in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()
    if "return_command" not in target:
        assert "fixture.manifest:fixture" in stderr.getvalue()
        assert target in stderr.getvalue()


@pytest.mark.parametrize(
    ("target", "status"),
    [
        ("tests.test_command_registry:_factory_raises_system_exit", 17),
        ("tests.test_command_registry:_create_configure_system_exit_command", 18),
        ("tests.test_command_registry:_create_run_system_exit_command", 19),
    ],
)
def test_command_system_exit_is_contained_as_exit_one(
    target: str,
    status: int,
) -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(1, "fixture", "Fixture.", frozenset(), target)
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stderr = StringIO()

    result = dispatch(
        ["fixture"],
        registry=registry,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 1
    assert f"SystemExit({status})" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_arbitrary_base_exception_is_contained_as_exit_one() -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "tests.test_command_registry:_create_base_exception_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stderr = StringIO()

    result = dispatch(
        ["fixture"],
        registry=registry,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 1
    assert stderr.getvalue() == "base exploded\n"
    assert "Traceback" not in stderr.getvalue()


@pytest.mark.parametrize("quiet", [False, True])
def test_command_error_preserves_exit_class_and_honors_quiet(quiet: bool) -> None:
    from taut.commands import CommandError, CommandSpec, GlobalOption
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset({GlobalOption.QUIET}),
        "tests.test_command_registry:_create_command_error_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stderr = StringIO()

    result = dispatch(
        ["fixture", *(["--quiet"] if quiet else [])],
        registry=registry,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 2
    assert stderr.getvalue() == ("" if quiet else "nothing matched\n")
    with pytest.raises(ValueError, match="exit_code must be 1 or 2"):
        CommandError("invalid", exit_code=0)


@pytest.mark.parametrize("value", ["parse exploded", "none"])
def test_parse_system_exit_is_contained_as_exit_one(value: str) -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "tests.test_command_registry:_create_parse_system_exit_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stderr = StringIO()

    result = dispatch(
        ["fixture", value],
        registry=registry,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 1
    assert f"unexpected SystemExit({None if value == 'none' else value!r})" in (
        stderr.getvalue()
    )
    assert "Traceback" not in stderr.getvalue()


def test_broken_unselected_implementation_does_not_break_healthy_dispatch() -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    healthy = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "tests.test_command_registry:_create_echo_command",
    )
    broken = CommandSpec(
        1,
        "broken",
        "Broken.",
        frozenset(),
        "missing_unselected_module:create",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "broken",
                "broken.manifest:broken",
                broken,
                _Distribution("broken-owner"),
            ),
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                healthy,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()

    result = dispatch(
        ["fixture", "healthy"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert result == 0
    assert stdout.getvalue().startswith("healthy|")


def test_broken_unselected_manifest_does_not_break_healthy_dispatch() -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    healthy = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "broken",
                "broken.manifest:broken",
                RuntimeError("broken manifest"),
                _Distribution("broken-owner"),
            ),
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                healthy,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stdout = StringIO()

    result = dispatch(
        ["fixture", "healthy"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert result == 0
    assert stdout.getvalue().startswith("healthy|")


@pytest.mark.parametrize("broken_field", ["metadata", "version"])
def test_broken_distribution_provenance_isolated_from_root_help(
    broken_field: str,
) -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _BrokenDistribution(broken_field),
            ),
        )
    )
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["--help"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "fixture      unavailable" in stdout.getvalue()
    assert f"distribution {broken_field} exploded" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_equal_owner_sort_keys_still_produce_byte_identical_conflicts_and_help() -> (
    None
):
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "fixture.command:create",
    )
    entries = (
        _EntryPoint(
            "fixture",
            "zeta.manifest:fixture",
            manifest,
            _Distribution("Foo"),
        ),
        _EntryPoint(
            "fixture",
            "alpha.manifest:fixture",
            manifest,
            _Distribution("foo"),
        ),
    )
    forward = CommandRegistry(entry_points=entries)
    reverse = CommandRegistry(entry_points=reversed(entries))
    forward_help = StringIO()
    reverse_help = StringIO()

    forward_result = dispatch(
        ["--help"],
        registry=forward,
        stdin=StringIO(),
        stdout=forward_help,
        stderr=StringIO(),
    )
    reverse_result = dispatch(
        ["--help"],
        registry=reverse,
        stdin=StringIO(),
        stdout=reverse_help,
        stderr=StringIO(),
    )

    assert forward_result == reverse_result == 0
    assert forward.get("fixture").error == reverse.get("fixture").error
    assert forward_help.getvalue() == reverse_help.getvalue()


def test_invalid_entry_point_name_is_diagnostic_not_a_help_command() -> None:
    from taut.commands import CommandSpec
    from taut.commands._registry import CommandRegistry

    invalid = CommandSpec(
        1,
        "Bad_Name",
        "Invalid.",
        frozenset(),
        "invalid.command:create",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "Bad_Name",
                "invalid.manifest:command",
                invalid,
                _Distribution("invalid-owner"),
            ),
        )
    )

    assert "Bad_Name" not in registry.names()
    assert registry.diagnostics() == (
        "command 'Bad_Name' from invalid-owner 1.0.0 "
        "(invalid.manifest:command) is unavailable: command name must match "
        "[a-z][a-z0-9-]*",
    )


def test_root_help_lists_unavailable_commands_and_emits_each_diagnostic_once() -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    builtin_claim = CommandSpec(
        1,
        "say",
        "Counterfeit say.",
        frozenset(),
        "counterfeit.command:create",
    )
    invalid = CommandSpec(
        1,
        "Bad_Name",
        "Invalid.",
        frozenset(),
        "invalid.command:create",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "broken",
                "broken.manifest:command",
                RuntimeError("manifest exploded"),
                _Distribution("broken-owner"),
            ),
            _EntryPoint(
                "say",
                "counterfeit.manifest:say",
                builtin_claim,
                _Distribution("counterfeit-owner"),
            ),
            _EntryPoint(
                "Bad_Name",
                "invalid.manifest:command",
                invalid,
                _Distribution("invalid-owner"),
            ),
        )
    )
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["--help"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "broken       unavailable" in stdout.getvalue()
    expected = {
        *registry.diagnostics(),
        registry.get("broken").error,
    }
    assert None not in expected
    warning_lines = stderr.getvalue().splitlines()
    assert set(warning_lines) == {f"warning: {message}" for message in expected}
    assert len(warning_lines) == len(expected)


def test_dispatch_escapes_dynamic_usage_help_registry_and_error_text() -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    probe = "\x1b]52;c;Y2xpcGJvYXJk\x07\x9b[31m\r\b\t\n"
    escaped = r"\x1b]52;c;Y2xpcGJvYXJk\a\x9b[31m\r\b\t\n"
    manifest = CommandSpec(
        1,
        "fixture",
        f"summary {probe}",
        frozenset(),
        "tests.test_command_registry:_create_echo_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution(f"owner{probe}"),
            ),
            _EntryPoint(
                "unavailable",
                "broken.manifest:command",
                RuntimeError(f"manifest {probe}"),
                _Distribution(f"broken-owner{probe}"),
            ),
        )
    )

    for argv in ([f"--bad{probe}"], ["fixture", "ok", f"--bad{probe}"]):
        stdout = StringIO()
        stderr = StringIO()
        result = dispatch(
            argv,
            registry=registry,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
        assert result == 1
        assert escaped in stderr.getvalue()

    stdout = StringIO()
    stderr = StringIO()
    assert (
        dispatch(
            ["--help"],
            registry=registry,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )
    assert f"summary {escaped}" in stdout.getvalue()
    assert escaped in stderr.getvalue()

    stderr = StringIO()
    assert (
        dispatch(
            ["unavailable"],
            registry=registry,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
        )
        == 1
    )
    assert escaped in stderr.getvalue()

    broken = CommandSpec(
        1,
        "fixture",
        "broken",
        frozenset(),
        "missing_fixture_module:create",
    )
    broken_registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                broken,
                _Distribution(f"owner{probe}"),
            ),
        )
    )
    stderr = StringIO()
    assert (
        dispatch(
            ["fixture"],
            registry=broken_registry,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
        )
        == 1
    )
    assert f"owner{escaped}" in stderr.getvalue()

    execution = CommandSpec(
        1,
        "fixture",
        "execution",
        frozenset(),
        "tests.test_command_registry:_create_control_error_command",
    )
    execution_registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                execution,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stderr = StringIO()
    assert (
        dispatch(
            ["fixture"],
            registry=execution_registry,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
        )
        == 1
    )
    assert r"failed\x1b]0;title\a\x9b\r\b\t\nrow" in stderr.getvalue()
    for output in (stdout.getvalue(), stderr.getvalue()):
        assert all(
            character == "\n"
            or not (ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F)
            for character in output
        )


def test_manifest_discovery_has_no_runtime_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from taut.commands._registry import CommandRegistry

    fixture_root = Path(__file__).parent / "fixtures" / "taut_command_plugin"
    monkeypatch.syspath_prepend(str(fixture_root))
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("taut_command_plugin", None)
    sys.modules.pop("taut_command_plugin.manifest", None)
    sys.modules.pop("taut_command_plugin.command", None)
    entry_point = metadata.EntryPoint(
        name="fixture",
        value="taut_command_plugin.manifest:fixture",
        group="taut.commands",
    )
    threads_before = tuple(threading.enumerate())
    signals_before = {
        candidate: signal.getsignal(candidate)
        for candidate in (signal.SIGINT, signal.SIGTERM)
    }
    files_before = tuple(tmp_path.iterdir())

    registry = CommandRegistry(entry_points=(entry_point,))

    assert registry.get("fixture").spec is not None
    assert tuple(threading.enumerate()) == threads_before
    assert {
        candidate: signal.getsignal(candidate)
        for candidate in (signal.SIGINT, signal.SIGTERM)
    } == signals_before
    assert tuple(tmp_path.iterdir()) == files_before
    assert "taut_command_plugin.manifest" in sys.modules
    assert "taut_command_plugin.command" not in sys.modules


def test_installed_wheel_is_discovered_and_dispatched(
    installed_command_fixture: Any,
) -> None:
    completed = installed_command_fixture.run_python(
        "from taut.commands._dispatch import dispatch; "
        "raise SystemExit(dispatch(['fixture', 'installed']))"
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "fixture:installed\n"
    assert completed.stderr == ""


def test_installed_console_discovers_then_loses_uninstalled_command(
    installed_command_fixture: Any,
    tmp_path: Path,
) -> None:
    isolated = installed_command_fixture.create_isolated(tmp_path / "console-env")

    present = isolated.run_console("fixture", "installed")
    assert present.returncode == 0, present.stderr
    assert present.stdout == "fixture:installed\n"
    assert present.stderr == ""

    uninstall = isolated.uninstall_plugin()
    assert uninstall.returncode == 0, uninstall.stderr

    absent = isolated.run_console("fixture", "installed")
    assert absent.returncode == 1
    assert absent.stdout == ""
    assert "unknown command: fixture" in absent.stderr
    assert "Traceback" not in absent.stderr


@pytest.mark.parametrize(
    ("args", "expected_exit", "stream_name", "fragment"),
    [
        ((), 1, "stderr", "usage: taut"),
        (("--help",), 0, "stdout", "usage: taut"),
        (("-h",), 0, "stdout", "usage: taut"),
        (("--version",), 0, "stdout", "taut "),
        (("--wat", "whoami"), 1, "stderr", "unrecognized root option"),
        (("nosuchverb",), 1, "stderr", "unknown command: nosuchverb"),
        (("--db",), 1, "stderr", "argument --db: expected one value"),
        (("--", "say"), 1, "stderr", "usage: taut say"),
        (("--", "summon"), 1, "stderr", "requires the taut-summon extension"),
        (("summon", "--help"), 1, "stderr", "requires the taut-summon extension"),
    ],
)
def test_installed_console_root_contract_and_python311_summon_sentinel(
    installed_command_fixture: Any,
    args: tuple[str, ...],
    expected_exit: int,
    stream_name: str,
    fragment: str,
) -> None:
    completed = installed_command_fixture.run_console(*args)

    assert completed.returncode == expected_exit
    selected = completed.stdout if stream_name == "stdout" else completed.stderr
    other = completed.stderr if stream_name == "stdout" else completed.stdout
    assert fragment in selected
    assert other == ""
    assert "Traceback" not in completed.stderr


def test_dispatch_reuses_and_closes_one_lazy_client() -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "tests.test_command_registry:_create_client_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    clients: list[_DisposableClient] = []
    received: list[dict[str, object]] = []

    def create_client(**kwargs: object) -> _DisposableClient:
        received.append(kwargs)
        client = _DisposableClient()
        clients.append(client)
        return client

    stdout = StringIO()
    result = dispatch(
        ["--db", "chat.db", "--as", "Ada", "--token", "secret", "fixture"],
        registry=registry,
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
        client_factory=create_client,
    )

    assert result == 0
    assert stdout.getvalue() == "true\n"
    assert received == [{"db_path": "chat.db", "as_name": "Ada", "token": "secret"}]
    assert len(clients) == 1
    assert clients[0].closed is True


def test_primary_command_error_wins_over_cleanup_error() -> None:
    from taut.commands import CommandSpec
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    manifest = CommandSpec(
        1,
        "fixture",
        "Fixture.",
        frozenset(),
        "tests.test_command_registry:_create_failing_client_command",
    )
    registry = CommandRegistry(
        entry_points=(
            _EntryPoint(
                "fixture",
                "fixture.manifest:fixture",
                manifest,
                _Distribution("fixture-owner"),
            ),
        )
    )
    stderr = StringIO()

    result = dispatch(
        ["fixture"],
        registry=registry,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
        client_factory=lambda **_kwargs: _DisposableClient(close_error=True),
    )

    assert result == 1
    assert stderr.getvalue() == "primary command failure\n"


def test_generic_dispatcher_does_not_add_command_specific_error_hints() -> None:
    from taut.commands import CommandContext
    from taut.commands._dispatch import _render_execution_error

    stderr = StringIO()
    context = CommandContext(
        db_path=None,
        as_name=None,
        auth_token=None,
        json=False,
        timestamps=False,
        quiet=False,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    result = _render_execution_error(
        context,
        RuntimeError("message id is ambiguous"),
    )

    assert result == 1
    assert stderr.getvalue() == "message id is ambiguous\n"


def _seed_channel(db_path: Path, *names: str, thread: str = "general") -> None:
    from taut.client import TautClient

    TautClient.init(db_path=str(db_path))
    for name in names:
        client = TautClient(db_path=str(db_path), as_name=name)
        try:
            client.join(thread)
        finally:
            client.close()


def _dispatch_static(
    argv: list[str],
    *,
    stdin: StringIO | None = None,
) -> tuple[int, str, str]:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    stdout = StringIO()
    stderr = StringIO()
    result = dispatch(
        argv,
        registry=CommandRegistry(entry_points=()),
        stdin=stdin if stdin is not None else StringIO(),
        stdout=stdout,
        stderr=stderr,
    )
    return result, stdout.getvalue(), stderr.getvalue()


def test_registry_say_posts_json_through_real_client(tmp_path: Path) -> None:
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [
            "--db",
            str(db_path),
            "--as",
            "van",
            "say",
            "general",
            "hello",
            "--json",
        ],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0, stderr.getvalue()
    records = [json.loads(line) for line in stdout.getvalue().splitlines()]
    message_record = records[-1]
    timestamp = message_record.pop("ts")
    assert isinstance(timestamp, int)
    assert len(str(timestamp)) == 19
    assert message_record == {
        "thread": "general",
        "from_id": message_record["from_id"],
        "from": "van",
        "kind": "message",
        "text": "hello",
    }
    assert isinstance(message_record["from_id"], str)
    assert message_record["from_id"].startswith("m_")
    assert stderr.getvalue() == ""
    client = TautClient(db_path=str(db_path), as_name="van")
    try:
        assert [message.text for message in client.log("general")][-1] == "hello"
    finally:
        client.close()


@pytest.mark.parametrize(
    ("text_args", "stdin_text", "expected"),
    [
        (("",), "unused", ""),
        (("snowman ☃\nsecond line",), "unused", "snowman ☃\nsecond line"),
        (("-",), "from stdin\n", "from stdin\n"),
        ((), "piped body", "piped body"),
    ],
)
def test_registry_say_text_sources_preserve_exact_text(
    tmp_path: Path,
    text_args: tuple[str, ...],
    stdin_text: str,
    expected: str,
) -> None:
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")

    result = dispatch(
        [
            "--db",
            str(db_path),
            "--as",
            "van",
            "say",
            "general",
            *text_args,
        ],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(stdin_text),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert result == 0
    client = TautClient(db_path=str(db_path), as_name="van")
    try:
        assert client.log("general")[-1].text == expected
    finally:
        client.close()


def test_registry_say_invalid_utf8_stdin_fails_before_write(tmp_path: Path) -> None:
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    stdin = TextIOWrapper(BytesIO(b"\xff"), encoding="utf-8")
    stderr = StringIO()
    try:
        result = dispatch(
            ["--db", str(db_path), "--as", "van", "say", "general", "-"],
            registry=CommandRegistry(entry_points=()),
            stdin=stdin,
            stdout=StringIO(),
            stderr=stderr,
        )
    finally:
        stdin.close()

    assert result == 1
    assert "stdin is not valid UTF-8" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()
    client = TautClient(db_path=str(db_path), as_name="van")
    try:
        assert [message.text for message in client.log("general")] == [
            "van created #general"
        ]
    finally:
        client.close()


def test_registry_say_omitted_text_on_tty_is_clean_error(tmp_path: Path) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    class TTYStringIO(StringIO):
        def isatty(self) -> bool:
            return True

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    stderr = StringIO()

    result = dispatch(
        ["--db", str(db_path), "--as", "van", "say", "general"],
        registry=CommandRegistry(entry_points=()),
        stdin=TTYStringIO(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert result == 1
    assert stderr.getvalue() == "message text required\n"


def test_registry_say_routes_to_real_subthread(tmp_path: Path) -> None:
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    setup = TautClient(db_path=str(db_path), as_name="van")
    try:
        root = setup.say("general", "root")
        child = setup.reply("general", str(root.ts), "first reply").thread
    finally:
        setup.close()

    result = dispatch(
        ["--db", str(db_path), "--as", "van", "say", child, "second reply"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert result == 0
    client = TautClient(db_path=str(db_path), as_name="van")
    try:
        assert [message.text for message in client.log(child)][-1] == "second reply"
    finally:
        client.close()


def test_registry_say_routes_to_real_direct_message(tmp_path: Path) -> None:
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van", "bob")
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [
            "--db",
            str(db_path),
            "--as",
            "van",
            "say",
            "@bob",
            "private",
            "--json",
        ],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0, stderr.getvalue()
    thread = json.loads(stdout.getvalue())["thread"]
    assert thread.startswith("dm.")
    bob = TautClient(db_path=str(db_path), as_name="bob")
    try:
        assert any(message.text == "private" for message in bob.read_unread())
    finally:
        bob.close()


def test_registry_say_notification_warning_stays_on_stderr(tmp_path: Path) -> None:
    from simplebroker import Queue

    from taut import addressing
    from taut._constants import META_QUEUE_NAME
    from taut._exceptions import EmptyResultError
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry
    from taut.state import SQLITE_SQL_DIALECT, SqlSidecarTautState

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van", "bob")
    members = TautClient(db_path=str(db_path))
    try:
        by_name = {member.name: member.member_id for member in members.who()}
    finally:
        members.close()
    thread = addressing.dm_queue_name(by_name["van"], by_name["bob"])
    queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        SqlSidecarTautState(queue, SQLITE_SQL_DIALECT).upsert_thread(
            name=thread,
            kind="dm",
            parent=None,
            origin_ts=None,
            created_by=by_name["van"],
            meta={},
            created_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [
            "--db",
            str(db_path),
            "--as",
            "van",
            "say",
            "@bob",
            "hi @bob",
            "--json",
        ],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    record = json.loads(stdout.getvalue())
    assert record["thread"] == thread
    assert "warning" not in record
    assert stderr.getvalue() == (
        "warning: mention notifications suppressed: direct-message registry "
        f"row for {thread} lacks participant metadata\n"
    )
    bob = TautClient(db_path=str(db_path), as_name="bob")
    try:
        with pytest.raises(EmptyResultError, match="nothing pending"):
            bob.inbox()
    finally:
        bob.close()


@pytest.mark.parametrize(
    ("flags", "output_kind"),
    [
        ((), "empty"),
        (("-t",), "timestamp"),
        (("--timestamps",), "timestamp"),
        (("--json",), "json"),
        (("--json", "-t"), "json"),
        (("-q",), "empty"),
        (("--quiet",), "empty"),
    ],
)
def test_registry_say_rendering_modes(
    tmp_path: Path,
    flags: tuple[str, ...],
    output_kind: str,
) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [
            "--db",
            str(db_path),
            "--as",
            "van",
            "say",
            "general",
            "rendered",
            *flags,
        ],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0, stderr.getvalue()
    assert stderr.getvalue() == ""
    if output_kind == "empty":
        assert stdout.getvalue() == ""
    elif output_kind == "timestamp":
        assert re.fullmatch(r"\d{19}\n", stdout.getvalue())
    else:
        assert json.loads(stdout.getvalue())["text"] == "rendered"
        assert len(stdout.getvalue().splitlines()) == 1


@pytest.mark.parametrize("quiet", [False, True])
def test_registry_say_json_identity_creation_prelude_is_legacy_compatible(
    tmp_path: Path,
    quiet: bool,
) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "bob")
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [
            "--db",
            str(db_path),
            "--as",
            "van",
            "say",
            "@bob",
            "hello",
            "--json",
            *(["--quiet"] if quiet else []),
        ],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0, stderr.getvalue()
    records = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert "token" in records[0]
    assert "ts" not in records[0]
    if quiet:
        # Characterize the legacy one-time token prelude under --json --quiet.
        assert len(records) == 1
    else:
        assert records[1]["text"] == "hello"
    assert stderr.getvalue() == ""


def test_shared_creation_renderer_preserves_quiet_candidate_note(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient
    from taut.commands._rendering import emit_created_member

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    client = TautClient(db_path=str(db_path), as_name="van")
    try:
        client.last_created_member = client.whoami()
        client.last_candidates = [("Ada", ["same executable"])]
        stdout = StringIO()
        stderr = StringIO()

        emit_created_member(
            client,
            json_output=False,
            quiet=True,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        client.close()

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (
        "note: you may be one of these:\n  Ada  same executable\n"
    )


def test_registry_say_post_globals_override_pre_globals_on_real_state(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    wrong_db = tmp_path / "wrong.db"
    right_db = tmp_path / "right.db"
    TautClient.init(db_path=str(wrong_db))
    _seed_channel(right_db, "van")
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [
            "--db",
            str(wrong_db),
            "--as",
            "wrong",
            "say",
            "general",
            "right target",
            f"--db={right_db}",
            "--as=van",
            "-t",
        ],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0, stderr.getvalue()
    assert re.fullmatch(r"\d{19}\n", stdout.getvalue())
    client = TautClient(db_path=str(right_db), as_name="van")
    try:
        message = client.log("general")[-1]
        assert message.text == "right target"
        assert message.from_name == "van"
    finally:
        client.close()


@pytest.mark.parametrize("separator_before_verb", [False, True])
def test_registry_say_literal_separator_posts_option_like_text(
    tmp_path: Path,
    separator_before_verb: bool,
) -> None:
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    prefix = ["--db", str(db_path), "--as", "van"]
    argv = (
        [*prefix, "--", "say", "general", "--json"]
        if separator_before_verb
        else [*prefix, "say", "general", "--", "--json"]
    )

    result = dispatch(
        argv,
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert result == 0
    client = TautClient(db_path=str(db_path), as_name="van")
    try:
        assert client.log("general")[-1].text == "--json"
    finally:
        client.close()


def test_registry_say_uses_only_injected_streams(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["--db", str(db_path), "--as", "van", "--json", "say", "general"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO("injected body"),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0, stderr.getvalue()
    assert json.loads(stdout.getvalue())["text"] == "injected body"
    assert stderr.getvalue() == ""
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_registry_say_help_does_not_initialize_client() -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    calls: list[dict[str, object]] = []
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["say", "--help"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
        client_factory=lambda **kwargs: calls.append(kwargs),
    )

    assert result == 0
    assert "usage: taut say" in stdout.getvalue()
    assert "TARGET" in stdout.getvalue()
    assert "explicit SQLite database path" in stdout.getvalue()
    assert "continuity, not authentication" in stdout.getvalue()
    assert "successful stdout records as NDJSON" in stdout.getvalue()
    assert stderr.getvalue() == ""
    assert calls == []


@pytest.mark.parametrize(
    "verb",
    [
        "init",
        "join",
        "leave",
        "who",
        "whoami",
        "rejoin",
        "set",
        "reply",
        "read",
        "inbox",
        "log",
        "list",
        "rename",
        "watch",
    ],
)
def test_registry_command_help_resolves_adapter(verb: str) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        [verb, "--help"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
        client_factory=lambda **_kwargs: pytest.fail("help initialized a client"),
    )

    assert result == 0
    assert f"usage: taut {verb}" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_registry_identity_membership_lifecycle_uses_real_state(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=str(db_path))
    root = ["--db", str(db_path)]

    result, out, err = _dispatch_static(
        [*root, "--as", "van", "--json", "join", "general", "--persona", "builder"]
    )
    assert result == 0, err
    joined = [json.loads(line) for line in out.splitlines()]
    assert joined[0]["name"] == "van"
    assert joined[0]["persona"] == "builder"
    assert joined[0]["token"]
    assert joined[1]["thread"] == "general"
    assert joined[1]["text"] == "van created #general"
    assert err == ""

    result, out, err = _dispatch_static([*root, "who", "general", "--json"])
    assert result == 0, err
    assert [record["name"] for record in map(json.loads, out.splitlines())] == ["van"]

    result, out, err = _dispatch_static(
        [*root, "--as", "van", "whoami", "--explain", "--json"]
    )
    assert result == 0, err
    identity = json.loads(out)
    assert identity["name"] == "van"
    assert identity["persona"] == "builder"
    assert isinstance(identity["explain"], dict)

    result, out, err = _dispatch_static(
        [*root, "--as", "van", "set", "name", "vanna", "--json"]
    )
    assert result == 0, err
    renamed = json.loads(out)
    assert renamed["name"] == "vanna"
    assert renamed["aliases"] == []

    result, out, err = _dispatch_static([*root, "--as", "van", "whoami", "--json"])
    assert result == 2
    assert out == ""
    assert err == "member not found: van\n"

    result, out, err = _dispatch_static(
        [*root, "--as", "vanna", "leave", "general", "--json"]
    )
    assert result == 0, err
    left = json.loads(out)
    assert left["thread"] == "general"
    assert left["text"] == "vanna left"

    result, out, err = _dispatch_static([*root, "who", "general", "--json"])
    assert result == 0, err
    assert out == ""


def test_registry_join_and_whoami_human_streams_and_token_boundary(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=str(db_path))
    root = ["--db", str(db_path), "--as", "van"]

    result, out, err = _dispatch_static(
        [*root, "join", "general", "--persona", "builder", "-t"]
    )
    assert result == 0
    assert re.search(r"\d{19}", out)
    assert "van created #general" in out
    assert "created new identity 'van'" in err
    assert "token:" in err

    result, out, err = _dispatch_static([*root, "whoami", "--explain"])
    assert result == 0, err
    lines = out.splitlines()
    assert lines[0].startswith(r"van\tagent\t")
    assert lines[0].endswith("  builder")
    assert isinstance(json.loads(lines[1]), dict)
    assert "token" not in out.lower()
    assert err == ""

    result, out, err = _dispatch_static(["--db", str(db_path), "who", "--json"])
    assert result == 0, err
    assert "token" not in json.loads(out)


def test_registry_join_new_and_nested_set_usage_match_cli(tmp_path: Path) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=str(db_path))
    root = ["--db", str(db_path), "--as", "van"]
    assert _dispatch_static([*root, "join", "general"])[0] == 0

    result, out, err = _dispatch_static([*root, "join", "other", "--new"])
    assert result == 1
    assert out == ""
    assert "member name already exists: van" in err

    result, out, err = _dispatch_static([*root, "set"])
    assert result == 1
    assert out == ""
    assert "the following arguments are required: PROPERTY" in err

    result, out, err = _dispatch_static([*root, "set", "name", "--help"])
    assert result == 0, err
    assert "New unique member name" in out
    assert err == ""


@pytest.mark.parametrize(
    "selector_position",
    [
        "local-token",
        "local-token-abbreviation",
        "local-token-equals",
        "global-token",
        "as",
    ],
)
def test_registry_rejoin_selector_forms(
    tmp_path: Path,
    selector_position: str,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=str(db_path))
    setup = TautClient(db_path=str(db_path), as_name="van")
    try:
        setup.join("general")
        assert setup.last_created_member is not None
        token = setup.last_created_member.token
        assert token is not None
    finally:
        setup.close()
    root = ["--db", str(db_path)]
    if selector_position == "local-token":
        argv = [*root, "rejoin", "--token", token, "--json"]
    elif selector_position == "local-token-abbreviation":
        argv = [*root, "rejoin", "--t", token, "--json"]
    elif selector_position == "local-token-equals":
        argv = [*root, "rejoin", f"--token={token}", "--json"]
    elif selector_position == "global-token":
        argv = [*root, "--token", token, "rejoin", "--json"]
    else:
        argv = [*root, "--as", "van", "rejoin", "--json"]

    result, out, err = _dispatch_static(argv)

    assert result == 0, err
    assert json.loads(out)["name"] == "van"


def test_registry_join_does_not_accept_abbreviated_post_verb_global(
    tmp_path: Path,
) -> None:
    result, out, err = _dispatch_static(
        [
            "--db",
            str(tmp_path / "chat.db"),
            "join",
            "general",
            "--tok",
            "continuity-token",
        ]
    )

    assert result == 1
    assert out == ""
    assert "unrecognized arguments: --tok continuity-token" in err


@pytest.mark.parametrize("token_before_verb", [False, True])
def test_registry_rejoin_rejects_name_plus_token(
    tmp_path: Path,
    token_before_verb: bool,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=str(db_path))
    setup = TautClient(db_path=str(db_path), as_name="van")
    try:
        setup.join("general")
        assert setup.last_created_member is not None
        token = setup.last_created_member.token
        assert token is not None
    finally:
        setup.close()
    root = ["--db", str(db_path)]
    argv = (
        [*root, "--token", token, "rejoin", "van"]
        if token_before_verb
        else [*root, "rejoin", "van", "--token", token]
    )

    result, out, err = _dispatch_static(argv)

    assert result == 1
    assert out == ""
    assert "exactly one" in err


@pytest.mark.parametrize("conflict", ["global-plus-local", "global-token-plus-as"])
def test_registry_rejoin_rejects_other_selector_conflicts(
    tmp_path: Path,
    conflict: str,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=str(db_path))
    setup = TautClient(db_path=str(db_path), as_name="van")
    try:
        setup.join("general")
        assert setup.last_created_member is not None
        token = setup.last_created_member.token
        assert token is not None
    finally:
        setup.close()
    root = ["--db", str(db_path), "--token", token]
    argv = (
        [*root, "rejoin", "--token", token]
        if conflict == "global-plus-local"
        else [*root, "--as", "van", "rejoin"]
    )

    result, out, err = _dispatch_static(argv)

    assert result == 1
    assert out == ""
    assert "exactly one" in err


def test_registry_identity_not_found_paths_keep_exit_two(tmp_path: Path) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=str(db_path))
    root = ["--db", str(db_path)]

    result, out, err = _dispatch_static([*root, "who", "missing"])
    assert result == 2
    assert out == ""
    assert err == "thread not found: missing\n"

    result, out, err = _dispatch_static([*root, "rejoin", "missing"])
    assert result == 2
    assert out == ""
    assert err == "member not found\n"


def test_registry_identity_guest_and_invalid_token_exit_classes(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=str(db_path))
    root = ["--db", str(db_path)]

    result, out, err = _dispatch_static([*root, "who", "--json"])
    assert result == 0
    assert out == err == ""

    result, out, err = _dispatch_static([*root, "whoami", "--json"])
    assert result == 2
    assert out == ""
    assert err == "unrecognized caller\n"

    result, out, err = _dispatch_static(
        [*root, "--token", "not-a-real-token", "who", "--json"]
    )
    assert result == 1
    assert out == ""
    assert "TAUT_TOKEN does not match" in err

    result, out, err = _dispatch_static([*root, "set", "name", "vanna", "--json"])
    assert result == 2
    assert out == ""
    assert err == "unrecognized caller\n"


def test_registry_leave_not_member_and_set_collision_exit_classes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van", "bob")
    root = ["--db", str(db_path)]

    result, out, err = _dispatch_static(
        [*root, "--as", "van", "leave", "general", "--quiet"]
    )
    assert result == 0, err
    assert out == err == ""

    result, out, err = _dispatch_static([*root, "--as", "van", "leave", "general"])
    assert result == 2
    assert out == ""
    assert err == "van is not a member of general\n"

    result, out, err = _dispatch_static(
        [*root, "--as", "bob", "set", "name", "van", "--json"]
    )
    assert result == 1
    assert out == ""
    assert "already exists" in err


def test_registry_reply_full_suffix_and_stdin_use_real_state(tmp_path: Path) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    setup = TautClient(db_path=str(db_path), as_name="van")
    try:
        first = setup.say("general", "first root")
        second = setup.say("general", "second root")
        ids = [str(message.ts) for message in setup.log("general")]
    finally:
        setup.close()
    second_id = str(second.ts)
    suffix = next(
        second_id[-length:]
        for length in range(4, len(second_id) + 1)
        if sum(candidate.endswith(second_id[-length:]) for candidate in ids) == 1
    )
    root = ["--db", str(db_path), "--as", "van", "reply", "general"]

    result, out, err = _dispatch_static([*root, str(first.ts), "full reply", "--json"])
    assert result == 0, err
    assert json.loads(out)["thread"] == f"general.{first.ts}"

    result, out, err = _dispatch_static(
        [*root, suffix, "-", "--json"],
        stdin=StringIO("stdin reply\n"),
    )
    assert result == 0, err
    assert json.loads(out)["thread"] == f"general.{second.ts}"

    verify = TautClient(db_path=str(db_path), as_name="van")
    try:
        assert [message.text for message in verify.log(f"general.{first.ts}")] == [
            "full reply"
        ]
        assert [message.text for message in verify.log(f"general.{second.ts}")] == [
            "stdin reply\n"
        ]
    finally:
        verify.close()


def test_registry_reply_adds_usage_hint_only_for_message_id_failures(
    tmp_path: Path,
) -> None:
    from simplebroker import Queue

    from taut.client import TautClient
    from taut.envelope import encode_envelope

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    setup = TautClient(db_path=str(db_path), as_name="van")
    try:
        van_id = setup.whoami().member_id
        known_ids = {str(message.ts) for message in setup.log("general")}
    finally:
        setup.close()
    queue = Queue("general", db_path=str(db_path))
    try:
        first_ts = queue.generate_timestamp()
        second_ts = first_ts + 10_000
        queue.insert_messages(
            [
                (
                    encode_envelope(
                        from_id=van_id,
                        from_name="van",
                        kind="message",
                        text=text,
                    ),
                    timestamp,
                )
                for text, timestamp in (
                    ("first twin", first_ts),
                    ("second twin", second_ts),
                )
            ]
        )
    finally:
        queue.close()
    known_ids.update((str(first_ts), str(second_ts)))
    unknown_suffix = next(
        candidate
        for candidate in ("1111", "2222", "3333", "4444", "5555", "6666")
        if not any(message_id.endswith(candidate) for message_id in known_ids)
    )
    root = ["--db", str(db_path), "--as", "van", "reply"]

    result, out, err = _dispatch_static([*root, "general", str(first_ts)[-4:], "child"])
    assert result == 1
    assert out == ""
    assert "ambiguous message id suffix" in err
    assert "usage: taut reply THREAD MSG_ID [TEXT|-]" in err

    result, out, err = _dispatch_static([*root, "general", "123", "child"])
    assert result == 2
    assert out == ""
    assert "message id suffix must be at least 4 digits" in err
    assert "usage: taut reply THREAD MSG_ID [TEXT|-]" in err

    result, out, err = _dispatch_static(
        [*root, "general", "1000000000000000000", "child"]
    )
    assert result == 2
    assert out == ""
    assert "message not found: 1000000000000000000" in err
    assert "usage: taut reply THREAD MSG_ID [TEXT|-]" in err

    result, out, err = _dispatch_static([*root, "general", unknown_suffix, "child"])
    assert result == 2
    assert out == ""
    assert "message not found in the most recent 1,000 messages" in err
    assert "usage: taut reply THREAD MSG_ID [TEXT|-]" in err

    result, out, err = _dispatch_static([*root, "missing", "1234", "child"])
    assert result == 2
    assert out == ""
    assert err == "thread not found: missing\n"


def test_registry_reply_renders_notification_warning_after_real_write(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    setup = TautClient(db_path=str(db_path), as_name="van")
    try:
        parent = setup.say("general", "root")
    finally:
        setup.close()

    class WarningAfterReplyClient(TautClient):
        def reply(self, thread: str, msg_id: str, text: str) -> Any:
            message = super().reply(thread, msg_id, text)
            self.last_notification_warnings.append("injected reply warning")
            return message

    stdout = StringIO()
    stderr = StringIO()
    result = dispatch(
        [
            "--db",
            str(db_path),
            "--as",
            "van",
            "reply",
            "general",
            str(parent.ts),
            "child",
            "--json",
        ],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
        client_factory=WarningAfterReplyClient,
    )

    assert result == 0
    assert json.loads(stdout.getvalue())["text"] == "child"
    assert stderr.getvalue() == "warning: injected reply warning\n"


def test_registry_read_quiet_still_advances_cursor_and_json_reads_next_page(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van", "bob")
    bob = TautClient(db_path=str(db_path), as_name="bob")
    try:
        bob.say("general", "consumed quietly")
    finally:
        bob.close()
    root = ["--db", str(db_path), "--as", "van", "read", "general"]

    result, out, err = _dispatch_static([*root, "--quiet"])
    assert result == 0, err
    assert out == err == ""

    result, out, err = _dispatch_static(root)
    assert result == 2
    assert out == ""
    assert err == "nothing unread\n"

    bob = TautClient(db_path=str(db_path), as_name="bob")
    try:
        bob.say("general", "visible next")
    finally:
        bob.close()
    result, out, err = _dispatch_static([*root, "--json"])
    assert result == 0, err
    assert [json.loads(line)["text"] for line in out.splitlines()] == ["visible next"]


def test_registry_log_filters_without_advancing_cursor_and_keeps_exit_classes(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van", "bob")
    bob = TautClient(db_path=str(db_path), as_name="bob")
    try:
        old = bob.say("general", "old")
        latest = bob.say("general", "latest")
    finally:
        bob.close()
    root = ["--db", str(db_path), "--as", "van"]

    result, out, err = _dispatch_static(
        [
            *root,
            "log",
            "general",
            "--since",
            str(old.ts),
            "--limit",
            "1",
            "--json",
        ]
    )
    assert result == 0, err
    assert json.loads(out)["text"] == "latest"

    result, out, err = _dispatch_static([*root, "read", "general", "--json"])
    assert result == 0, err
    assert "latest" in [json.loads(line)["text"] for line in out.splitlines()]

    result, out, err = _dispatch_static(
        [*root, "log", "general", "--since", str(latest.ts), "--json"]
    )
    assert result == 2
    assert out == ""
    assert err == "empty\n"

    result, out, err = _dispatch_static([*root, "log", "general", "--limit", "0"])
    assert result == 1
    assert out == ""
    assert err == "limit must be positive\n"


def test_registry_read_and_log_human_output_stays_grouped(tmp_path: Path) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van", "bob")
    bob = TautClient(db_path=str(db_path), as_name="bob")
    try:
        bob.say("general", "grouped through registry")
    finally:
        bob.close()
    root = ["--db", str(db_path), "--as", "van"]

    result, out, err = _dispatch_static([*root, "log", "general"])
    assert result == 0, err
    lines = out.splitlines()
    assert "general" in lines[0]
    assert any("bob" in line and "grouped through registry" in line for line in lines)

    result, out, err = _dispatch_static([*root, "read", "general"])
    assert result == 0, err
    lines = out.splitlines()
    assert "general" in lines[0]
    assert any("bob" in line and "grouped through registry" in line for line in lines)


def test_registry_list_renders_unread_and_dm_metadata_from_real_state(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van", "bob")
    bob = TautClient(db_path=str(db_path), as_name="bob")
    try:
        bob.say("general", "unread")
    finally:
        bob.close()
    van = TautClient(db_path=str(db_path), as_name="van")
    try:
        dm_thread = van.say("@bob", "private").thread
        member_ids = {member.member_id for member in van.who()}
    finally:
        van.close()
    root = ["--db", str(db_path), "--as", "van", "list"]

    result, out, err = _dispatch_static(root)
    assert result == 0, err
    assert re.search(r"^general  \d+ unread$", out, re.MULTILINE)

    result, out, err = _dispatch_static([*root, "--all", "--json"])
    assert result == 0, err
    records = {record["thread"]: record for record in map(json.loads, out.splitlines())}
    assert records[dm_thread]["kind"] == "dm"
    assert set(records[dm_thread]["members"]) == member_ids


def test_registry_inbox_claims_pointers_keeps_source_and_renders_human_actions(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van", "bob")
    van = TautClient(db_path=str(db_path), as_name="van")
    try:
        first = van.say("general", "hello @bob")
    finally:
        van.close()
    root = ["--db", str(db_path), "--as", "bob", "inbox"]

    result, out, err = _dispatch_static([*root, "--json"])
    assert result == 0, err
    notification = json.loads(out)
    assert notification["type"] == "mention"
    assert notification["message_ts"] == first.ts

    result, out, err = _dispatch_static([*root, "--json"])
    assert result == 2
    assert out == ""
    assert err == "nothing pending\n"

    van = TautClient(db_path=str(db_path), as_name="van")
    try:
        second = van.say("general", "again @bob")
    finally:
        van.close()
    result, out, err = _dispatch_static(root)
    assert result == 0, err
    assert "inspect: taut log general" in out
    assert re.search(r"reply: taut reply general \d{4,19}", out)

    bob = TautClient(db_path=str(db_path), as_name="bob")
    try:
        source_ids = {message.ts for message in bob.log("general")}
    finally:
        bob.close()
    assert {first.ts, second.ts} <= source_ids


def test_registry_rename_moves_subthreads_and_honors_render_modes(
    tmp_path: Path,
) -> None:
    from taut.client import TautClient

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    setup = TautClient(db_path=str(db_path), as_name="van")
    try:
        root_message = setup.say("general", "root")
        setup.reply("general", str(root_message.ts), "child")
    finally:
        setup.close()
    root = ["--db", str(db_path), "rename"]

    result, out, err = _dispatch_static([*root, "general", "ops", "--json"])
    assert result == 0, err
    assert json.loads(out)["thread"] == "ops"

    verify = TautClient(db_path=str(db_path), as_name="van")
    try:
        assert [message.text for message in verify.log("ops")][-1] == "root"
        assert [message.text for message in verify.log(f"ops.{root_message.ts}")] == [
            "child"
        ]
    finally:
        verify.close()

    result, out, err = _dispatch_static([*root, "ops", "work"])
    assert result == 0, err
    assert out == "renamed ops to work\n"

    result, out, err = _dispatch_static([*root, "work", "final", "--quiet"])
    assert result == 0, err
    assert out == err == ""


def test_registry_rename_resumes_matching_interrupted_operation(
    tmp_path: Path,
) -> None:
    from simplebroker import Queue

    from taut._constants import META_QUEUE_NAME
    from taut.client import TautClient
    from taut.state import SQLITE_SQL_DIALECT, SqlSidecarTautState

    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")
    queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        SqlSidecarTautState(queue, SQLITE_SQL_DIALECT).start_channel_rename(
            old_name="general",
            new_name="ops",
            affected=[{"old": "general", "new": "ops"}],
            started_ts=queue.generate_timestamp(),
        )
    finally:
        queue.close()
    root = ["--db", str(db_path)]

    result, out, err = _dispatch_static([*root, "log", "general"])
    assert result == 1
    assert out == ""
    assert "run 'taut rename general ops' to finish it" in err

    result, out, err = _dispatch_static([*root, "rename", "general", "ops", "--json"])
    assert result == 0, err
    assert json.loads(out)["thread"] == "ops"

    verify = TautClient(db_path=str(db_path), as_name="van")
    try:
        assert verify.list_threads(all_threads=True)[0].name == "ops"
    finally:
        verify.close()


def test_registry_watch_sigint_path_stops_watcher_and_closes_client() -> None:
    from taut.client import Message, Notification
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    message_text = "live\nmessage\x1b]52;c;Y2xpcGJvYXJk\x07\x9b"
    actor_name = "bob\x1b]0;title\x07\t"
    items: list[Message | Notification] = [
        Message(
            thread="general",
            ts=1_785_000_000_000_000_001,
            from_id="m_" + "a" * 26,
            from_name="van",
            kind="message",
            text=message_text,
        ),
        Notification(
            type="reply",
            to_id="m_" + "a" * 26,
            actor_id="m_" + "b" * 26,
            actor_name=actor_name,
            thread="general.1785000000000000001",
            message_ts=1_785_000_000_000_000_002,
        ),
    ]

    class CountingStream(StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.flush_count = 0

        def flush(self) -> None:
            self.flush_count += 1
            super().flush()

    class InterruptingWatcher:
        def __init__(
            self,
            handler: Callable[[Message | Notification], None],
        ) -> None:
            self.handler = handler
            self.stop_calls: list[tuple[bool, float]] = []

        def run_forever(self) -> None:
            for item in items:
                self.handler(item)
            raise KeyboardInterrupt

        def stop(self, *, join: bool, timeout: float) -> None:
            self.stop_calls.append((join, timeout))

    class WatchClient:
        def __init__(self, **_kwargs: object) -> None:
            self.watcher: InterruptingWatcher | None = None
            self.closed = False
            self.threads: list[str] | None = None

        def watch(
            self,
            handler: Callable[[Message | Notification], None],
            *,
            threads: list[str] | None,
        ) -> InterruptingWatcher:
            self.threads = threads
            self.watcher = InterruptingWatcher(handler)
            return self.watcher

        def close(self) -> None:
            self.closed = True

    clients: list[WatchClient] = []

    def create_client(**kwargs: object) -> WatchClient:
        client = WatchClient(**kwargs)
        clients.append(client)
        return client

    stdout = CountingStream()
    result = dispatch(
        ["watch", "general", "ops", "--json"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=StringIO(),
        client_factory=create_client,
    )

    assert result == 0
    assert len(clients) == 1
    assert clients[0].threads == ["general", "ops"]
    assert clients[0].watcher is not None
    assert clients[0].watcher.stop_calls == [(True, 5.0)]
    assert clients[0].closed is True
    records = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert records[0]["text"] == message_text
    assert records[1]["actor_name"] == actor_name
    assert records[1]["type"] == "reply"
    assert stdout.flush_count == 2

    human_stdout = CountingStream()
    human_stderr = StringIO()
    result = dispatch(
        ["watch", "general", "ops"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=human_stdout,
        stderr=human_stderr,
        client_factory=create_client,
    )

    assert result == 0
    assert r"live\nmessage\x1b]52;c;Y2xpcGJvYXJk\a\x9b" in (human_stdout.getvalue())
    assert r"bob\x1b]0;title\a\t" in human_stdout.getvalue()
    assert all(
        character == "\n"
        or not (ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F)
        for character in human_stdout.getvalue() + human_stderr.getvalue()
    )
    assert human_stdout.flush_count == 2


def test_registry_watch_unjoined_filter_keeps_exit_two(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    _seed_channel(db_path, "van")

    result, out, err = _dispatch_static(
        ["--db", str(db_path), "--as", "van", "watch", "missing"]
    )

    assert result == 2
    assert out == ""
    assert err == "not a member of watched thread(s): missing\n"


def test_registry_watch_flushes_dynamic_membership_and_preserves_broken_pipe_cursor(
    tmp_path: Path,
) -> None:
    from taut._exceptions import EmptyResultError
    from taut.client import TautClient
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    class ClosingStream(StringIO):
        def __init__(self, marker: str) -> None:
            super().__init__()
            self.marker = marker
            self.flush_count = 0
            self.broken = False
            self.break_on_flush = False
            self.close_called = False
            self.condition = threading.Condition()

        def write(self, text: str) -> int:
            with self.condition:
                if self.marker in text:
                    self.break_on_flush = True
                written = super().write(text)
                self.condition.notify_all()
                return written

        def flush(self) -> None:
            with self.condition:
                self.flush_count += 1
                if self.break_on_flush:
                    self.broken = True
                    self.condition.notify_all()
                    raise BrokenPipeError
                super().flush()
                self.condition.notify_all()

        def close(self) -> None:
            self.close_called = True

        def wait_for(self, fragment: str, timeout: float = 10.0) -> bool:
            with self.condition:
                return self.condition.wait_for(
                    lambda: fragment in StringIO.getvalue(self),
                    timeout=timeout,
                )

    def wait_until(predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    db_path = tmp_path / "chat.db"
    TautClient.init(db_path=str(db_path))
    van = TautClient(db_path=str(db_path), as_name="van")
    bob = TautClient(db_path=str(db_path), as_name="bob")
    try:
        van.join("home")
        bob.join("home")
        try:
            van.read_unread("home")
        except EmptyResultError:
            pass
        marker = "terminal sink marker"
        stdout = ClosingStream(marker)
        stderr = StringIO()
        results: list[int] = []

        worker = threading.Thread(
            target=lambda: results.append(
                dispatch(
                    ["--db", str(db_path), "--as", "van", "watch", "--json"],
                    registry=CommandRegistry(entry_points=()),
                    stdin=StringIO(),
                    stdout=stdout,
                    stderr=stderr,
                )
            ),
            daemon=True,
        )
        worker.start()

        bob.say("home", "first live record")
        assert stdout.wait_for("first live record")
        assert stdout.flush_count >= 1

        def home_cursor_advanced() -> bool:
            return not next(
                thread.unread
                for thread in van.list_threads(all_threads=True)
                if thread.name == "home"
            )

        assert wait_until(home_cursor_advanced)

        van.join("late")
        bob.join("late")
        bob.say("late", "dynamic membership record")
        assert stdout.wait_for("dynamic membership record")

        bob.say("home", marker)
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert results == [0]
        assert stdout.broken is True
        assert stdout.close_called is True
        assert stderr.getvalue() == ""

        unread = van.read_unread("home")
        assert marker in [message.text for message in unread]
    finally:
        van.close()
        bob.close()


def test_registry_init_is_idempotent_and_honors_render_modes(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"

    result, out, err = _dispatch_static(["init", "--db", str(db_path), "--json"])
    assert result == 0, err
    assert json.loads(out) == {"db": str(db_path), "created": True}
    assert err == ""

    result, out, err = _dispatch_static(["--db", str(db_path), "init"])
    assert result == 0, err
    assert out == f"exists: {db_path}\n"
    assert err == ""

    result, out, err = _dispatch_static(["init", f"--db={db_path}", "--quiet"])
    assert result == 0
    assert out == err == ""
