"""Explicit extension launch and dependency-boundary tests.

Spec references:
- docs/specs/10-taut-tui.md [TUI-3.1], [TUI-3.2]
"""

from __future__ import annotations

import sys
from importlib.metadata import EntryPoint
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.sqlite_only


class _TTYStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _dispatch_static(argv: list[str]) -> tuple[int, str, str]:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    stdout = StringIO()
    stderr = StringIO()
    result = dispatch(
        argv,
        registry=CommandRegistry(
            entry_points=(
                EntryPoint(
                    name="tui",
                    value="taut_tui.command_manifest:tui",
                    group="taut.commands",
                ),
            )
        ),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )
    return result, stdout.getvalue(), stderr.getvalue()


def test_root_help_lists_explicit_tui_command() -> None:
    result, stdout, stderr = _dispatch_static(["--help"])

    assert result == 0
    assert "tui" in stdout
    assert "human-first" in stdout
    assert stderr == ""


def test_tui_help_loads_adapter_but_not_textual_runtime() -> None:
    sys.modules.pop("textual", None)
    sys.modules.pop("taut_tui.app", None)

    result, _stdout, stderr = _dispatch_static(["tui", "--help"])

    assert result == 0
    assert "textual" not in sys.modules
    assert "taut_tui.app" not in sys.modules
    assert stderr == ""


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["--db", "before.db", "tui"], ("before.db", None, None)),
        (["tui", "--db", "after.db"], ("after.db", None, None)),
        (["--as", "Ada", "tui"], (None, "Ada", None)),
        (["tui", "--as", "Ada"], (None, "Ada", None)),
        (["--token", "continuity", "tui"], (None, None, "continuity")),
        (["tui", "--token", "continuity"], (None, None, "continuity")),
    ],
)
def test_supported_identity_and_storage_globals_reach_launch(
    monkeypatch: pytest.MonkeyPatch,
    tokens: list[str],
    expected: tuple[str | None, str | None, str | None],
) -> None:
    import taut_tui

    captured: list[tuple[str | None, str | None, str | None]] = []

    def capture_launch(
        *,
        db_path: str | None,
        as_name: str | None,
        continuity_token: str | None,
    ) -> int:
        captured.append((db_path, as_name, continuity_token))
        return 0

    monkeypatch.setattr(taut_tui, "launch", capture_launch)

    result, stdout, stderr = _dispatch_static(tokens)

    assert result == 0
    assert captured == [expected]
    assert stdout == ""
    assert stderr == ""


@pytest.mark.parametrize("option", ["--json", "-t", "--timestamps", "-q", "--quiet"])
def test_preverb_unsupported_global_fails_before_textual_import(option: str) -> None:
    sys.modules.pop("textual", None)

    result, stdout, stderr = _dispatch_static([option, "tui"])

    assert result == 1
    assert stdout == ""
    assert "taut tui does not accept" in stderr
    assert "Traceback" not in stderr
    assert "textual" not in sys.modules


@pytest.mark.parametrize("option", ["--json", "-t", "--timestamps", "-q", "--quiet"])
def test_postverb_unsupported_global_is_a_usage_error(option: str) -> None:
    result, stdout, stderr = _dispatch_static(["tui", option])

    assert result == 1
    assert stdout == ""
    assert f"unrecognized arguments: {option}" in stderr
    assert "Traceback" not in stderr


def test_non_tty_fails_before_textual_import_or_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    created: list[dict[str, Any]] = []
    stderr = StringIO()
    sys.modules.pop("textual", None)
    monkeypatch.setattr(sys, "stdin", StringIO())
    monkeypatch.setattr(sys, "stdout", StringIO())

    result = dispatch(
        ["tui"],
        registry=CommandRegistry(
            entry_points=(
                EntryPoint(
                    name="tui",
                    value="taut_tui.command_manifest:tui",
                    group="taut.commands",
                ),
            )
        ),
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=stderr,
        client_factory=lambda **kwargs: created.append(kwargs),
    )

    assert result == 1
    assert "interactive input and output terminals" in stderr.getvalue()
    assert created == []
    assert "textual" not in sys.modules


@pytest.mark.parametrize("non_tty_name", ["stdin", "stdout"])
def test_each_ambient_terminal_is_required(
    monkeypatch: pytest.MonkeyPatch,
    non_tty_name: str,
) -> None:
    from taut_tui import TuiLaunchError, _launch

    monkeypatch.setattr(_launch.sys, "stdin", _TTYStringIO())
    monkeypatch.setattr(_launch.sys, "stdout", _TTYStringIO())
    monkeypatch.setattr(_launch.sys, non_tty_name, StringIO())

    with pytest.raises(TuiLaunchError, match="interactive input and output"):
        _launch.run_tui(db_path=None, as_name=None, continuity_token=None)


def test_missing_textual_dependency_has_one_actionable_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui import _launch

    real_import = _launch.importlib.import_module

    def missing_textual(name: str) -> object:
        if name == "textual":
            raise ModuleNotFoundError("No module named 'textual'", name="textual")
        return real_import(name)

    monkeypatch.setattr(_launch.importlib, "import_module", missing_textual)
    monkeypatch.setattr(_launch.sys, "stdin", _TTYStringIO())
    monkeypatch.setattr(_launch.sys, "stdout", _TTYStringIO())

    from taut_tui import MissingTuiDependencyError

    with pytest.raises(
        MissingTuiDependencyError, match="pip install 'taut-tui'"
    ) as caught:
        _launch.run_tui(
            db_path=None,
            as_name=None,
            continuity_token=None,
        )

    assert type(caught.value).__name__ == "MissingTuiDependencyError"


def test_installed_core_wheel_does_not_claim_the_extension_command(
    installed_command_fixture: Any,
) -> None:
    result = installed_command_fixture.run_python(
        "import io; "
        "from taut.commands._dispatch import dispatch; "
        "out=io.StringIO(); err=io.StringIO(); "
        "assert dispatch(['tui'], stdin=io.StringIO(), stdout=out, stderr=err) == 1; "
        "assert 'unknown command: tui' in err.getvalue(); "
        "assert 'Traceback' not in err.getvalue()"
    )

    assert result.returncode == 0, result.stderr


def test_installed_tui_extension_wheel_runs_real_headless_app(
    installed_command_fixture: Any,
    tmp_path: Path,
) -> None:
    isolated = installed_command_fixture.create_isolated(tmp_path / "wheel-with-tui")
    installed = isolated.install_wheels(isolated.tui_wheel)
    assert installed.returncode == 0, installed.stderr

    result = isolated.run_python(
        "import asyncio\n"
        "from taut_tui.app import TautApp\n"
        "async def probe():\n"
        " app=TautApp(db_path=None, as_name=None, continuity_token=None)\n"
        " async with app.run_test(size=(80, 24)) as pilot:\n"
        "  await pilot.pause()\n"
        "  assert app.query_one('#conversation').display is True\n"
        "asyncio.run(probe())"
    )

    assert result.returncode == 0, result.stderr


def test_broken_textual_transitive_import_preserves_original_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui import _launch

    failure = ModuleNotFoundError("No module named 'rich.segment'", name="rich.segment")

    def broken_textual(name: str) -> object:
        if name == "textual":
            raise failure
        raise AssertionError(name)

    monkeypatch.setattr(_launch.importlib, "import_module", broken_textual)
    monkeypatch.setattr(_launch.sys, "stdin", _TTYStringIO())
    monkeypatch.setattr(_launch.sys, "stdout", _TTYStringIO())

    with pytest.raises(ModuleNotFoundError) as caught:
        _launch.run_tui(db_path=None, as_name=None, continuity_token=None)

    assert caught.value is failure


def test_broken_installed_textual_is_not_mislabelled_as_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut_tui import _launch

    failure = ModuleNotFoundError("No module named 'rich.segment'", name="rich.segment")

    def broken_import(name: str) -> object:
        if name == "textual":
            return object()
        if name == "taut_tui.app":
            raise failure
        raise AssertionError(name)

    monkeypatch.setattr(_launch.importlib, "import_module", broken_import)
    monkeypatch.setattr(_launch.sys, "stdin", _TTYStringIO())
    monkeypatch.setattr(_launch.sys, "stdout", _TTYStringIO())

    with pytest.raises(ModuleNotFoundError) as caught:
        _launch.run_tui(
            db_path=None,
            as_name=None,
            continuity_token=None,
        )

    assert caught.value is failure
    assert "pip install 'taut-tui'" not in str(caught.value)
