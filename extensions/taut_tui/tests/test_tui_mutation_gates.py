"""Portable causal REDs, distinct from native Windows qualification."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from _mutation_probe_child import (
    CASES,
    Edit,
    MutationCase,
    load_result,
    require_red,
    run_case,
)
from tests.helpers.terminal_probe import HostTerminal

pytestmark = pytest.mark.sqlite_only


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_retained_matrix_mutation_fails_only_its_semantic_assertion(
    tmp_path: Path, case: MutationCase
) -> None:
    require_red(run_case(case, tmp_path), case)


def test_host_terminal_ownership_keeps_real_unread_output_per_run() -> None:
    """Portable fixture ownership only, not pending ReadFile/ConPTY evidence."""
    first = HostTerminal.open()
    second: HostTerminal | None = None
    try:
        old_marker = b"OLD-HOST-UNREAD\n"
        new_marker = b"NEW-HOST-OUTPUT\n"
        assert os.write(first.lease_output_fd, old_marker) == len(old_marker)
        # No reader has consumed the first real host's pending output.
        second = HostTerminal.open()
        assert os.write(second.lease_output_fd, new_marker) == len(new_marker)
        output = second.read_until(b"NEW-HOST-OUTPUT", timeout=2)
        assert b"NEW-HOST-OUTPUT" in output, "new host output was not consumed"
        assert b"OLD-HOST-UNREAD" not in output, "host output crossed run ownership"
        assert second is not first
        pending = first.read_until(b"OLD-HOST-UNREAD", timeout=2)
        assert b"OLD-HOST-UNREAD" in pending, "first host lost its unread output"
    finally:
        if second is not None and second is not first:
            second.close()
        first.close()


@pytest.mark.parametrize(
    "fault", ("exit", "setup", "marker", "extra", "timeout", "collection", "internal")
)
def test_mutation_gate_rejects_nonsemantic_child_failures(fault: str) -> None:
    case = CASES[0]
    result: dict[str, Any] = {
        "exit": 1,
        "pytest_exit": 1,
        "timed_out": False,
        "collection_errors": 0,
        "internal_errors": 0,
        "reports": [
            {
                "node": case.node,
                "phase": phase,
                "outcome": outcome,
                "exception": exception,
                "semantic": semantic,
            }
            for phase, outcome, exception, semantic in (
                ("setup", "passed", None, False),
                ("call", "failed", case.exception, True),
                ("teardown", "passed", None, False),
            )
        ],
    }
    if fault == "exit":
        result["exit"] = 0
    elif fault == "setup":
        result["reports"][0]["outcome"] = "failed"
    elif fault == "marker":
        result["reports"][1]["semantic"] = False
    elif fault == "extra":
        result["reports"].append(result["reports"][1])
    elif fault in ("collection", "internal"):
        result[f"{fault}_errors"] = 1
    else:
        result["timed_out"] = True
    with pytest.raises(AssertionError):
        require_red(result, case)


def test_mutation_gate_requires_a_child_report(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="no structured result"):
        load_result(tmp_path / "missing.json", CASES[0])


def test_mutation_child_deadline_kills_and_reaps_instead_of_accepting_red(
    tmp_path: Path,
) -> None:
    host_case = next(case for case in CASES if case.name == "host-object-reuse")
    blocked = replace(
        host_case,
        edits=(
            Edit(
                "tests/test_tui_mutation_gates.py",
                "    first = HostTerminal.open()\n",
                '    __import__("threading").Event().wait()\n'
                "    first = HostTerminal.open()\n",
            ),
        ),
    )
    # The known target's body blocks. Timeout is not an unknown-case or import
    # failure, and cannot be accepted as the expected semantic failure.
    result = run_case(blocked, tmp_path, timeout=1)
    assert result["timed_out"] is True
    assert isinstance(result["exit"], int)  # wait() reaped the exact killed child.
    with pytest.raises(AssertionError, match="containment expired"):
        require_red(result, host_case)
