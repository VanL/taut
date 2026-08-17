"""Executable disposition matrix for mirrored command paths."""

from __future__ import annotations

import pytest

from taut.commands.syntax import command_nodes, core_command_syntax
from taut_tui.actions import ActionId
from taut_tui.command_bindings import COMMAND_BINDINGS, binding_for

pytestmark = pytest.mark.sqlite_only


def test_every_core_leaf_has_one_explicit_tui_disposition() -> None:
    leaves = {
        command.path
        for command in command_nodes(core_command_syntax())
        if not command.children
    }

    assert leaves == set(COMMAND_BINDINGS) - {("summon",), ("dismiss",)}
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
