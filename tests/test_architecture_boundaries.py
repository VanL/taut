from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from taut_summon._control import _ControlReactor

from taut._broker_retry import is_transient_broker_error
from taut.watcher import (
    REACTOR_LIFECYCLE_METHODS,
    BaseReactor,
    TautWatcher,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOTS = (
    PROJECT_ROOT / "taut",
    PROJECT_ROOT / "extensions" / "taut_pg" / "taut_pg",
    PROJECT_ROOT / "extensions" / "taut_summon" / "taut_summon",
)

pytestmark = pytest.mark.shared


def test_production_code_uses_public_simplebroker_surface_only() -> None:
    offenders: list[str] = []

    for root in PACKAGE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for needle in (
                "simplebroker._",
                'getattr(broker, "_',
                "broker._runner",
                "broker._retrieve",
            ):
                if needle in text:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {needle}")

    assert offenders == []


@pytest.mark.parametrize("reactor_type", [TautWatcher, _ControlReactor])
def test_first_party_reactors_inherit_guarded_lifecycle_templates(
    reactor_type: type[BaseReactor],
) -> None:
    for method_name in REACTOR_LIFECYCLE_METHODS:
        assert getattr(reactor_type, method_name) is getattr(BaseReactor, method_name)


def test_legacy_retry_import_shim_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="upgrade taut-summon"):
        is_transient_broker_error(RuntimeError("database is locked"))


class _RuntimeImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.modules: set[str] = set()
        self.local_modules: set[str] = set()
        self._function_depth = 0

    def visit_If(self, node: ast.If) -> None:
        if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            for statement in node.orelse:
                self.visit(statement)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        destination = self.local_modules if self._function_depth else self.modules
        destination.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is not None:
            destination = self.local_modules if self._function_depth else self.modules
            destination.add(node.module)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1


@pytest.mark.parametrize(
    ("relative_path", "expected", "expected_local"),
    [
        (
            Path("taut/__init__.py"),
            {"taut._constants", "taut._exceptions"},
            set(),
        ),
        (
            Path("taut/_constants.py"),
            set(),
            {"simplebroker"},
        ),
        (
            Path("taut/cli.py"),
            {"taut.commands._dispatch"},
            set(),
        ),
        (
            Path("taut/commands/say.py"),
            {"taut.commands._protocol", "taut.commands._rendering"},
            set(),
        ),
        *(
            (
                Path(f"taut/commands/{verb}.py"),
                {"taut.commands._protocol", "taut.commands._rendering"},
                set(),
            )
            for verb in (
                "join",
                "leave",
                "who",
                "whoami",
                "rejoin",
                "set",
                "read",
                "inbox",
                "log",
                "list",
                "rename",
            )
        ),
        (
            Path("taut/commands/reply.py"),
            {
                "taut._exceptions",
                "taut.commands._protocol",
                "taut.commands._rendering",
            },
            set(),
        ),
        (
            Path("taut/commands/init.py"),
            {"taut.commands._protocol", "taut.commands._rendering"},
            {"taut.client"},
        ),
        (
            Path("taut/commands/watch.py"),
            {"taut.commands._protocol", "taut.commands._rendering"},
            {"simplebroker.ext"},
        ),
        (
            Path("taut/commands/_summon_compat.py"),
            {"taut.commands._protocol"},
            {"taut_summon.cli"},
        ),
        (
            Path("taut/commands/_rendering.py"),
            {"taut._exceptions"},
            {"taut.client"},
        ),
        (Path("taut/commands/_protocol.py"), set(), {"taut.client"}),
        (
            Path("taut/commands/__init__.py"),
            {"taut.commands._protocol"},
            set(),
        ),
        (
            Path("extensions/taut_summon/taut_summon/cli.py"),
            {"taut.commands", "taut_summon.commands", "taut_summon.models"},
            {
                "taut_summon.commands.dismiss",
                "taut_summon.commands.summon",
                "taut_summon.controller",
            },
        ),
        (
            Path("extensions/taut_summon/taut_summon/command_manifest.py"),
            {"taut.commands"},
            set(),
        ),
        (
            Path("extensions/taut_summon/taut_summon/commands/__init__.py"),
            {"taut.commands"},
            set(),
        ),
        (
            Path("extensions/taut_summon/taut_summon/commands/summon.py"),
            {"taut.commands", "taut_summon.commands", "taut_summon.models"},
            {"taut_summon.controller", "taut_summon.interaction"},
        ),
        (
            Path("extensions/taut_summon/taut_summon/commands/dismiss.py"),
            {"taut.commands", "taut_summon.commands", "taut_summon.models"},
            {"taut_summon.controller"},
        ),
        (
            Path("extensions/taut_summon/taut_summon/interaction.py"),
            set(),
            set(),
        ),
    ],
)
def test_command_leaf_runtime_imports_stay_at_command_seams(
    relative_path: Path,
    expected: set[str],
    expected_local: set[str],
) -> None:
    visitor = _RuntimeImportVisitor()
    visitor.visit(ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8")))
    nonstdlib = {
        module
        for module in visitor.modules
        if module != "__future__"
        and module.partition(".")[0] not in sys.stdlib_module_names
    }
    local_nonstdlib = {
        module
        for module in visitor.local_modules
        if module != "__future__"
        and module.partition(".")[0] not in sys.stdlib_module_names
    }

    assert nonstdlib == expected
    assert local_nonstdlib == expected_local
