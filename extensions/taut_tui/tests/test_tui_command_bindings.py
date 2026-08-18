"""Executable disposition matrix for mirrored command paths."""

from __future__ import annotations

import pytest

from taut.commands.syntax import (
    command_nodes,
    core_command_syntax,
    merge_command_syntax,
)
from taut_tui.actions import ActionId
from taut_tui.command_bindings import COMMAND_BINDINGS, binding_for
from taut_tui.command_syntax import provide_syntax

pytestmark = pytest.mark.sqlite_only


def test_every_core_leaf_has_one_explicit_tui_disposition() -> None:
    leaves = {
        command.path
        for command in command_nodes(core_command_syntax())
        if not command.children
    }

    tui_only = {("summon",), ("dismiss",), ("q",), ("quit",)}
    assert leaves == set(COMMAND_BINDINGS) - tui_only
    assert all(binding_for(path) is not None for path in leaves)


def test_cli_only_and_action_linked_bindings_are_explicit() -> None:
    watch = binding_for(("watch",))
    system_load = binding_for(("system", "load"))
    init = binding_for(("init",))
    summon = binding_for(("summon",))
    assert watch is not None and watch.cli_only is True
    assert system_load is not None and system_load.cli_only is True
    assert init is not None and init.action_id is ActionId.WORKSPACE_INITIALIZE
    assert summon is not None and summon.action_id is ActionId.SUMMON_START
    assert binding_for(("unknown",)) is None


def test_quit_aliases_are_tui_local_and_guarded_action_owned() -> None:
    core_paths = {node.path for node in command_nodes(core_command_syntax())}
    tui_paths = {
        node.path
        for node in command_nodes(
            merge_command_syntax(core_command_syntax(), (provide_syntax(),))
        )
    }

    assert ("q",) not in core_paths
    assert ("quit",) not in core_paths
    assert {("q",), ("quit",)} <= tui_paths
    q_binding = binding_for(("q",))
    quit_binding = binding_for(("quit",))
    assert q_binding is not None
    assert quit_binding is not None
    assert q_binding.action_id is ActionId.APPLICATION_QUIT
    assert quit_binding.action_id is ActionId.APPLICATION_QUIT
