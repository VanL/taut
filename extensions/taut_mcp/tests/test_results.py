from __future__ import annotations

import subprocess
import sys

from taut_mcp._results import (
    DOMAIN_TOOL_NAMES,
    RECORD_TYPE_BY_TOOL,
    tool_result,
)
from taut_mcp._tools import TOOLS


def test_every_tool_has_a_record_type() -> None:
    assert set(RECORD_TYPE_BY_TOOL) == {tool.name for tool in TOOLS}
    assert DOMAIN_TOOL_NAMES == frozenset(RECORD_TYPE_BY_TOOL) - {
        "attach_workspace",
        "detach_workspace",
        "list_workspaces",
    }


def test_tool_result_omits_warnings_when_empty() -> None:
    assert tool_result([]) == {"records": []}
    assert tool_result([{"a": 1}], warnings=()) == {"records": [{"a": 1}]}
    assert tool_result([], warnings=("w",)) == {"records": [], "warnings": ["w"]}


def test_results_and_tools_import_without_the_client() -> None:
    probe = (
        "import sys, taut_mcp._results, taut_mcp._tools;"
        "print(sorted(m for m in sys.modules if m == 'taut' or m.startswith(('taut.', 'taut_mcp._commands'))))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "[]"
