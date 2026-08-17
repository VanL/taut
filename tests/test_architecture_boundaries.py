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
    PROJECT_ROOT / "extensions" / "taut_tui" / "taut_tui",
)

pytestmark = pytest.mark.shared


class _SimpleBrokerPrivateVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.module_aliases = {"simplebroker"}
        self.constructor_aliases = {"Queue", "SimpleBroker"}
        self.context_factory_aliases = {"open_broker"}
        self._broker_scopes: list[set[str]] = [set()]
        self.offenses: list[tuple[int, str]] = []

    @property
    def broker_instances(self) -> set[str]:
        return self._broker_scopes[-1]

    def _record(self, node: ast.AST, description: str) -> None:
        self.offenses.append((getattr(node, "lineno", 0), description))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.startswith("simplebroker._"):
                self._record(node, f"private import {alias.name}")
            elif alias.name == "simplebroker":
                self.module_aliases.add(alias.asname or "simplebroker")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module.startswith("simplebroker._"):
            self._record(node, f"private import {module}")
            return
        if module != "simplebroker":
            return
        for alias in node.names:
            if alias.name.startswith("_"):
                self._record(node, f"private import simplebroker.{alias.name}")
            elif alias.name in {"Queue", "SimpleBroker"}:
                self.constructor_aliases.add(alias.asname or alias.name)
            elif alias.name == "open_broker":
                self.context_factory_aliases.add(alias.asname or alias.name)

    def _is_broker_constructor(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.constructor_aliases
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.module_aliases
            and node.attr in {"Queue", "SimpleBroker"}
        )

    def _is_broker_context_factory(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.context_factory_aliases
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.module_aliases
            and node.attr == "open_broker"
        )

    def _is_broker_annotation(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Subscript):
            node = node.value
        return self._is_broker_constructor(node)

    def _is_broker_instance(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.broker_instances
        return isinstance(node, ast.Call) and self._is_broker_constructor(node.func)

    def _record_broker_target(self, target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self.broker_instances.add(target.id)

    def _forget_target(self, target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self.broker_instances.discard(target.id)
        elif isinstance(target, (ast.List, ast.Tuple)):
            for element in target.elts:
                self._forget_target(element)

    def visit_Assign(self, node: ast.Assign) -> None:
        is_broker = self._is_broker_instance(node.value)
        for target in node.targets:
            if is_broker:
                self._record_broker_target(target)
            else:
                self._forget_target(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._is_broker_annotation(node.annotation) or (
            node.value is not None and self._is_broker_instance(node.value)
        ):
            self._record_broker_target(node.target)
        else:
            self._forget_target(node.target)
        self.generic_visit(node)

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars is None:
                continue
            if isinstance(
                item.context_expr, ast.Call
            ) and self._is_broker_context_factory(item.context_expr.func):
                self._record_broker_target(item.optional_vars)
            else:
                self._forget_target(item.optional_vars)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        self._broker_scopes.append(set())
        try:
            arguments = (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
            for argument in arguments:
                if argument.annotation is not None and self._is_broker_annotation(
                    argument.annotation
                ):
                    self.broker_instances.add(argument.arg)
            for optional_argument in (node.args.vararg, node.args.kwarg):
                if (
                    optional_argument is not None
                    and optional_argument.annotation is not None
                    and self._is_broker_annotation(optional_argument.annotation)
                ):
                    self.broker_instances.add(optional_argument.arg)
            for statement in node.body:
                self.visit(statement)
        finally:
            self._broker_scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in (*node.decorator_list, *node.bases):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._broker_scopes.append(set())
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self._broker_scopes.pop()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_") and (
            (isinstance(node.value, ast.Name) and node.value.id in self.module_aliases)
            or self._is_broker_instance(node.value)
        ):
            owner = node.value.id if isinstance(node.value, ast.Name) else "constructor"
            self._record(node, f"private attribute {owner}.{node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and (
                (
                    isinstance(node.args[0], ast.Name)
                    and node.args[0].id in self.module_aliases
                )
                or self._is_broker_instance(node.args[0])
            )
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value.startswith("_")
        ):
            owner = (
                node.args[0].id if isinstance(node.args[0], ast.Name) else "constructor"
            )
            self._record(
                node,
                f"private getattr {owner}.{node.args[1].value}",
            )
        self.generic_visit(node)


def _simplebroker_private_offenses(source: str) -> list[tuple[int, str]]:
    visitor = _SimpleBrokerPrivateVisitor()
    visitor.visit(ast.parse(source))
    return visitor.offenses


def test_simplebroker_private_surface_scanner_handles_python_syntax() -> None:
    source = """
"simplebroker._prose is not code"
# simplebroker._comment is not code
import simplebroker as sb
from simplebroker import (
    SimpleBroker as Broker,
    Queue as WorkQueue,
    open_broker as connect,
    _private_helper,
)

first = sb.SimpleBroker({})
second = Broker({})
queue_handle = WorkQueue("jobs")
queue_alias = queue_handle
first._runner()
getattr(second, "_retrieve")()
queue_handle._runner()
queue_alias._runner()
sb.Queue("direct")._runner()
getattr(WorkQueue("direct-getattr"), "_retrieve")()

def annotated(queue_param: WorkQueue[str]) -> None:
    queue_param._runner()

typed_queue: WorkQueue[str]
typed_queue._runner()

def broker_owner() -> None:
    value = WorkQueue("scoped")
    value._runner()

def unrelated_scope() -> None:
    value = object()
    value._private_but_not_simplebroker()

def reassigned() -> None:
    handle = WorkQueue("temporary")
    handle = object()
    handle._private_but_not_simplebroker()

with connect("db") as opened:
    opened._retrieve()
"""

    assert [
        description for _line, description in _simplebroker_private_offenses(source)
    ] == [
        "private import simplebroker._private_helper",
        "private attribute first._runner",
        "private getattr second._retrieve",
        "private attribute queue_handle._runner",
        "private attribute queue_alias._runner",
        "private attribute constructor._runner",
        "private getattr constructor._retrieve",
        "private attribute queue_param._runner",
        "private attribute typed_queue._runner",
        "private attribute value._runner",
        "private attribute opened._retrieve",
    ]


def test_production_code_uses_public_simplebroker_surface_only() -> None:
    offenders: list[str] = []

    for root in PACKAGE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            for line, description in _simplebroker_private_offenses(
                path.read_text(encoding="utf-8")
            ):
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{line}: {description}"
                )

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
            {"simplebroker", "simplebroker.ext"},
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
                "channel",
                "search",
            )
        ),
        (
            Path("taut/commands/message.py"),
            {
                "taut._exceptions",
                "taut.commands._protocol",
                "taut.commands._rendering",
            },
            set(),
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
            {
                "taut._exceptions",
                "taut.commands._protocol",
                "taut.commands._rendering",
            },
            set(),
        ),
        (
            Path("taut/commands/_summon_compat.py"),
            {"taut.commands._protocol"},
            set(),
        ),
        (
            Path("extensions/taut_tui/taut_tui/command_manifest.py"),
            {"taut.commands"},
            set(),
        ),
        (
            Path("extensions/taut_tui/taut_tui/command.py"),
            {"taut.commands"},
            {"taut_tui"},
        ),
        (
            Path("extensions/taut_tui/taut_tui/__init__.py"),
            set(),
            {"taut_tui._launch"},
        ),
        (
            Path("extensions/taut_tui/taut_tui/_launch.py"),
            {"taut_tui"},
            {"taut.debug"},
        ),
        (
            Path("taut/commands/_rendering.py"),
            {"taut", "taut._exceptions"},
            {"simplebroker", "taut.client", "taut.search"},
        ),
        (
            Path("taut/commands/_protocol.py"),
            set(),
            {"taut.client", "taut.commands._rendering"},
        ),
        (
            Path("taut/commands/__init__.py"),
            {"taut.commands._protocol", "taut.commands.syntax"},
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
                "taut.debug",
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
            {"taut"},
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
        ("taut/commands/_rendering.py", "emit_doctor_report", ".write"),
        ("taut/commands/_rendering.py", "write_human_line", ".write"),
        ("taut/commands/_rendering.py", "write_human_line", ".write"),
        (
            "taut/commands/_summon_compat.py",
            "MissingSummonCommand.run",
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
