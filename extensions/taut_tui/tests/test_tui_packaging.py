"""Distribution and command-extension contracts for ``taut-tui``."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from taut.commands import GlobalOption


def test_tui_command_is_owned_by_the_extension_manifest() -> None:
    from taut_tui.command_manifest import tui

    assert tui.name == "tui"
    assert tui.summary == "Open Taut's human-first terminal interface."
    assert tui.post_verb_globals == frozenset(
        {GlobalOption.DB, GlobalOption.AS, GlobalOption.TOKEN}
    )
    assert tui.implementation == "taut_tui.command:create_command"
    assert tui.raw_stdio_transport is True


def test_distribution_registers_the_tui_command_entry_point() -> None:
    project = Path(__file__).parents[1] / "pyproject.toml"
    metadata = tomllib.loads(project.read_text(encoding="utf-8"))

    assert metadata["project"]["entry-points"]["taut.commands"] == {
        "tui": "taut_tui.command_manifest:tui"
    }


def test_core_does_not_own_the_tui_package_or_command() -> None:
    repository = Path(__file__).parents[3]

    assert not (repository / "taut" / "tui").exists()
    assert not (repository / "taut" / "commands" / "tui.py").exists()


def test_extension_uses_only_public_core_and_summon_modules() -> None:
    package = Path(__file__).parents[1] / "taut_tui"
    forbidden: list[str] = []

    for source in sorted(package.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = [node.module]
            else:
                continue
            for module in modules:
                if module.startswith(
                    ("taut._", "taut.client._", "taut.commands._", "taut_summon._")
                ):
                    forbidden.append(f"{source.name}: {module}")

    assert forbidden == []
