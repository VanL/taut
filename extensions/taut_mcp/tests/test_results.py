from __future__ import annotations

import subprocess
import sys

import pytest
from _result_schemas import RECORD_SCHEMAS, result_schema
from jsonschema import Draft202012Validator, ValidationError, validate

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


def test_record_type_map_covers_closed_test_schemas() -> None:
    assert set(RECORD_TYPE_BY_TOOL.values()) == set(RECORD_SCHEMAS)


@pytest.mark.parametrize("record_type", sorted(RECORD_SCHEMAS))
def test_closed_result_schema_accepts_only_records_and_nonempty_warnings(
    record_type: str,
) -> None:
    schema = result_schema(record_type)
    Draft202012Validator.check_schema(schema)
    validate(tool_result([]), schema)
    validate(tool_result([], warnings=("stalled",)), schema)
    with pytest.raises(ValidationError):
        validate({"records": [], "warnings": []}, schema)
    for field, value in (
        ("workspace", "/workspace"),
        ("empty", True),
        ("record_type", record_type),
        ("guidance", []),
        ("unexpected", True),
    ):
        with pytest.raises(ValidationError):
            validate({"records": [], field: value}, schema)
