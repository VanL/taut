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
            {"taut.commands._protocol", "taut.commands._rendering"},
            {"taut_summon.cli"},
        ),
        (
            Path("taut/commands/_rendering.py"),
            {"taut", "taut._exceptions"},
            {"taut.client"},
        ),
        (
            Path("taut/commands/_protocol.py"),
            set(),
            {"taut.client", "taut.commands._rendering"},
        ),
        (
            Path("taut/commands/__init__.py"),
            {"taut.commands._protocol"},
            set(),
        ),
        (
            Path("extensions/taut_summon/taut_summon/cli.py"),
            {
                "taut",
                "taut.commands",
                "taut_summon.commands",
                "taut_summon.models",
            },
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
            {"taut", "taut.commands"},
            set(),
        ),
        (
            Path("extensions/taut_summon/taut_summon/commands/summon.py"),
            {
                "taut",
                "taut.commands",
                "taut_summon.commands",
                "taut_summon.models",
            },
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


class _TerminalSinkVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: Path) -> None:
        self.relative_path = relative_path
        self.scope: list[str] = []
        self.sinks: list[tuple[str, str, str]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if (
            self.scope
            and self.scope[-1].endswith("ArgumentParser")
            and node.name in {"error", "exit"}
        ):
            self.sinks.append(
                (
                    self.relative_path.as_posix(),
                    ".".join([*self.scope, node.name]),
                    f"argparse.{node.name}",
                )
            )
        if (
            self.scope
            and self.scope[-1].endswith("Formatter")
            and node.name == "format"
        ):
            self.sinks.append(
                (
                    self.relative_path.as_posix(),
                    ".".join([*self.scope, node.name]),
                    "logging.format",
                )
            )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        kind: str | None = None
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            kind = "print"
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "write":
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                kind = "os.write"
            else:
                kind = ".write"
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logging"
            and node.func.attr in {"basicConfig", "StreamHandler"}
        ):
            kind = f"logging.{node.func.attr}"
        if kind is not None:
            self.sinks.append(
                (
                    self.relative_path.as_posix(),
                    ".".join(self.scope) or "<module>",
                    kind,
                )
            )
        self.generic_visit(node)


def test_first_party_terminal_sink_inventory_is_explicit() -> None:
    relative_paths = [
        *sorted(Path("taut/commands").glob("*.py")),
        Path("extensions/taut_summon/taut_summon/cli.py"),
        *sorted(Path("extensions/taut_summon/taut_summon/commands").glob("*.py")),
        Path("extensions/taut_summon/taut_summon/scripted_provider.py"),
        Path("extensions/taut_summon/taut_summon/_pty.py"),
    ]
    sinks: list[tuple[str, str, str]] = []
    for relative_path in relative_paths:
        visitor = _TerminalSinkVisitor(relative_path)
        visitor.visit(
            ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
        )
        sinks.extend(visitor.sinks)

    # Each entry is a reviewed sink. Duplicate tuples are intentional call
    # counts, so adding a write inside an allowed function still changes the
    # inventory. JSON/protocol/file writes preserve exact data; common line
    # writers and parser overrides escape text; bootstrap writes are fixed
    # ASCII; the named PTY writes are the byte-transparent SUM-7.4 exemption.
    expected = [
        ("taut/commands/_dispatch.py", "dispatch", ".write"),
        ("taut/commands/_dispatch.py", "_dispatch", ".write"),
        ("taut/commands/_dispatch.py", "_write_root_help", ".write"),
        (
            "taut/commands/_protocol.py",
            "CommandArgumentParser.error",
            "argparse.error",
        ),
        (
            "taut/commands/_protocol.py",
            "CommandArgumentParser.exit",
            "argparse.exit",
        ),
        ("taut/commands/_rendering.py", "write_json", ".write"),
        ("taut/commands/_rendering.py", "write_human_line", ".write"),
        ("taut/commands/_rendering.py", "write_human_line", ".write"),
        (
            "taut/commands/_summon_compat.py",
            "SummonCompatibilityCommand.run",
            ".write",
        ),
        ("extensions/taut_summon/taut_summon/cli.py", "main", ".write"),
        (
            "extensions/taut_summon/taut_summon/cli.py",
            "_SummonArgumentParser.error",
            "argparse.error",
        ),
        (
            "extensions/taut_summon/taut_summon/commands/__init__.py",
            "_write_human_line",
            ".write",
        ),
        (
            "extensions/taut_summon/taut_summon/commands/__init__.py",
            "_write_human_line",
            ".write",
        ),
        (
            "extensions/taut_summon/taut_summon/commands/summon.py",
            "_TerminalSafeFormatter.format",
            "logging.format",
        ),
        (
            "extensions/taut_summon/taut_summon/commands/summon.py",
            "_configure_logging",
            "logging.StreamHandler",
        ),
        (
            "extensions/taut_summon/taut_summon/scripted_provider.py",
            "_emit",
            "print",
        ),
        (
            "extensions/taut_summon/taut_summon/scripted_provider.py",
            "_record",
            ".write",
        ),
        (
            "extensions/taut_summon/taut_summon/scripted_provider.py",
            "_emit_raw",
            "print",
        ),
        (
            "extensions/taut_summon/taut_summon/scripted_provider.py",
            "_write_stderr",
            "print",
        ),
        (
            "extensions/taut_summon/taut_summon/_pty.py",
            "PtyHandle.attach._forward_wake",
            "os.write",
        ),
        (
            "extensions/taut_summon/taut_summon/_pty.py",
            "PtyHandle.attach",
            "os.write",
        ),
        (
            "extensions/taut_summon/taut_summon/_pty.py",
            "PtyHandle.attach",
            "os.write",
        ),
        (
            "extensions/taut_summon/taut_summon/_pty.py",
            "PtyHandle._write_all",
            "os.write",
        ),
        (
            "extensions/taut_summon/taut_summon/_pty.py",
            "PtyHandle._write_interrupt_fd_best_effort",
            "os.write",
        ),
    ]
    assert sorted(sinks) == sorted(expected)
