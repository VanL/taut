"""Scratch-only causal mutation runner with a content-free pytest protocol."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


@dataclass(frozen=True)
class Edit:
    path: str
    before: str
    after: str


@dataclass(frozen=True)
class MutationCase:
    name: str
    node: str
    exception: str
    marker: str
    edits: tuple[Edit, ...]


_PROBES = "tests/test_tui_determinism_probes.py"
_SOURCE = "test_real_dm_source_return_and_application_are_separate_owned_phases[0]"
_BUDGET = "test_real_setup_and_navigation_use_distinct_nonresetting_deadlines"
_SCREEN = "tests/_screen_completion.py"
_ORDER = "tests/test_tui_navigation_ordering.py"


def _case(
    name: str, file: str, test: str, exception: str, marker: str, *edits: Edit
) -> MutationCase:
    return MutationCase(name, f"{Path(file).name}::{test}", exception, marker, edits)


CASES = (
    _case(
        "operation-thread-authority",
        "tests/test_tui_summon.py",
        "test_terminal_lease_ownership_survives_distinct_driver_phase_threads",
        "AssertionError",
        "assert leased.is_set()",
        Edit(
            "taut_tui/summon.py",
            "notice, owner=self._token, cancel=cancel",
            "notice, owner=threading.current_thread(), cancel=cancel",
        ),
        Edit(
            "taut_tui/summon.py",
            "return self._owner._terminal_lease(owner=self._token)",
            "return self._owner._terminal_lease(owner=threading.current_thread())",
        ),
    ),
    _case(
        "wrong-budget-origin",
        _PROBES,
        _BUDGET + "[False]",
        "CompletionTimeout",
        "navigation.read",
        Edit(
            _PROBES,
            "behavior_deadline = scope.now() + 5",
            "behavior_deadline = setup_deadline - 30 + 5",
        ),
    ),
    _case(
        "reset-behavior-deadline",
        _PROBES,
        _BUDGET + "[True]",
        "Failed",
        "DID NOT RAISE",
        Edit(
            _PROBES,
            "clock[0] = 17.001 if behavior_late else 16.999",
            "clock[0] = 17.001 if behavior_late else 16.999\n"
            "            behavior_deadline = scope.now() + 5",
        ),
    ),
    _case(
        "mount-at-object-creation",
        "tests/test_screen_completion.py",
        "test_mount_observation_waits_for_actual_mount",
        "AssertionError",
        "assert screens.mounted(screen).snapshot() is None",
        Edit(
            _SCREEN,
            "        self.history.append(screen)",
            "        life.mounted.succeed(life.mounted.key, screen)\n"
            "        self.history.append(screen)",
        ),
    ),
    _case(
        "focus-uses-new-lifecycle",
        "tests/test_screen_completion.py",
        "test_inflight_old_focus_cannot_complete_a_reused_screen_generation",
        "AssertionError",
        "assert second.snapshot() is None",
        Edit(
            _SCREEN,
            "        await self._original_on_message(event)\n",
            "        await self._original_on_message(event)\n"
            "        if isinstance(event, events.DescendantFocus):\n"
            "            try:\n"
            "                life = self._lifecycles.get(event.widget.screen)\n"
            "            except NoScreen:\n"
            "                life = None\n",
        ),
    ),
    _case(
        "result-is-not-retirement",
        "tests/test_screen_completion.py",
        "test_result_delivery_does_not_complete_held_removal",
        "AssertionError",
        "assert screens.retired(screen).snapshot() is None",
        Edit(
            _SCREEN,
            "                life.result.succeed(life.result.key, value)",
            "                life.result.succeed(life.result.key, value)\n"
            "                life.retired.succeed(life.retired.key, life.screen)",
        ),
    ),
    _case(
        "search-owner-guard",
        _PROBES,
        "test_queued_old_highlight_cannot_replace_new_search_owner",
        "AssertionError",
        "assert app.visual_state.selected_message_id == hit.ts",
        Edit(
            "taut_tui/app.py",
            "            if self.visual_state.viewport.search_owned:\n",
            "            if False:\n",
        ),
    ),
    _case(
        "source-membership",
        _PROBES,
        _SOURCE,
        "AssertionError",
        "source missing committed DM",
        Edit(
            _PROBES,
            "                snapshot = original_read(session)\n",
            "                snapshot = original_read(session)\n"
            "                snapshot = replace(snapshot, direct_messages=())\n",
        ),
    ),
    _case(
        "source-original-error",
        _PROBES,
        _SOURCE,
        "ValueError",
        "source failed after real SQLite read",
        Edit(
            _PROBES,
            "                return snapshot\n",
            '                raise ValueError("source failed after real SQLite read")\n',
        ),
    ),
    _case(
        "owner-application",
        _PROBES,
        _SOURCE,
        "CompletionTimeout",
        "navigation.applied",
        Edit(
            _PROBES,
            "                    app.call_later(app.held_apply)\n",
            "                    # Causal mutant: drop this exact owner application.\n",
        ),
    ),
    _case(
        "widget-rendering",
        _PROBES,
        _SOURCE,
        "AssertionError",
        "rendered DM row missing",
        Edit(
            _PROBES,
            "                apply(done)\n",
            "                apply(done)\n"
            '                self.query_one("#navigation-list", TautOptionList).clear_options()\n',
        ),
    ),
    _case(
        "serialized-worker",
        _ORDER,
        "test_serialized_navigation_read_cannot_overtake_held_older_worker",
        "AssertionError",
        "assert not new_future.running()",
        Edit(
            "taut_tui/session.py",
            "            max_workers=1,",
            "            max_workers=2,",
        ),
        # Force the schedule at the real second worker's entry. The mutant's
        # second Future must stay running until the original test releases both
        # workers in its finally block, independent of thread-start scheduling.
        Edit(
            _ORDER,
            "    release = threading.Event()\n    history:",
            "    release = threading.Event()\n    second_entered = threading.Event()\n    history:",
        ),
        Edit(
            _ORDER,
            "            def new_read() -> NavigationSnapshot:\n",
            "            def new_read() -> NavigationSnapshot:\n"
            "                second_entered.set()\n"
            '                assert release.wait(5), "second worker was not released"\n',
        ),
        Edit(
            _ORDER,
            "            assert new_future is not old_future\n",
            '            assert second_entered.wait(2), "second worker did not enter"\n'
            "            assert new_future is not old_future\n",
        ),
    ),
    _case(
        "search-generation",
        _ORDER,
        "test_stale_real_search_callback_cannot_replace_newer_committed_dm_results",
        "AssertionError",
        "assert [hit.ts for hit in after_stale] == [new_message.ts]",
        Edit(
            "taut_tui/screens.py",
            "        if generation != self._generation:\n            return\n",
            "        # Causal mutant: accept the stale real search result.\n",
        ),
    ),
    _case(
        "host-object-reuse",
        "tests/test_tui_mutation_gates.py",
        "test_host_terminal_ownership_keeps_real_unread_output_per_run",
        "AssertionError",
        "host output crossed run ownership",
        Edit(
            "tests/test_tui_mutation_gates.py",
            "        second = HostTerminal.open()\n",
            "        second = first\n",
        ),
    ),
)


def _prepare(case: MutationCase, scratch: Path, *, mutate: bool) -> Path:
    source = Path(__file__).resolve().parent
    extension = scratch / "extensions" / "taut_tui"
    tests = extension / "tests"
    tests.mkdir(parents=True)
    shutil.copytree(
        source.parent / "taut_tui",
        extension / "taut_tui",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for helper in source.glob("_*.py"):
        shutil.copy2(helper, tests / helper.name)
    file = case.node.split("::", 1)[0]
    shutil.copy2(source / file, tests / file)
    shutil.copy2(source / "conftest.py", tests / "conftest.py")
    shutil.copy2(source.parent / "pyproject.toml", extension / "pyproject.toml")
    if mutate:
        for edit in case.edits:
            path = extension / edit.path
            original = path.read_text(encoding="utf-8")
            assert original.count(edit.before) == 1, (
                f"{case.name}: expected exactly one mutation boundary in {edit.path}"
            )
            path.write_text(original.replace(edit.before, edit.after), encoding="utf-8")
    return extension


def run_case(
    case: MutationCase, scratch: Path, *, mutate: bool = True, timeout: float = 45
) -> dict[str, Any]:
    """One child, one source mutation, one pytest invocation; never retry."""
    extension = _prepare(case, scratch, mutate=mutate)
    report = scratch / "mutation-result.json"
    root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    for key in ("TAUT_TUI_PHASE_DIR", "PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS"):
        env.pop(key, None)
    env["PYTHONPATH"] = os.pathsep.join(
        (str(extension), str(extension / "tests"), str(root))
    )
    # Real assertion output stays in the child. Only enumerated, content-free
    # result metadata crosses this boundary or is retained as an artifact.
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            case.name,
            str(extension),
            str(report),
        ],
        cwd=scratch,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    timed_out = False
    try:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
    if timed_out:
        return {"exit": process.returncode, "timed_out": True}
    result = load_result(report, case)
    result.update(exit=process.returncode, timed_out=False)
    return result


def load_result(report: Path, case: MutationCase) -> dict[str, Any]:
    assert report.is_file(), f"{case.name}: child produced no structured result"
    result: dict[str, Any] = json.loads(report.read_text(encoding="utf-8"))
    return result


def require_red(result: dict[str, Any], case: MutationCase) -> None:
    """Reject green, collection, setup, teardown, wrong failures and containment."""
    assert result.get("timed_out") is False, f"{case.name}: child containment expired"
    assert result.get("exit") == result.get("pytest_exit") == 1, result
    assert result.get("collection_errors") == result.get("internal_errors") == 0, result
    assert result.get("reports") == [
        {
            "node": case.node,
            "phase": "setup",
            "outcome": "passed",
            "exception": None,
            "semantic": False,
        },
        {
            "node": case.node,
            "phase": "call",
            "outcome": "failed",
            "exception": case.exception,
            "semantic": True,
        },
        {
            "node": case.node,
            "phase": "teardown",
            "outcome": "passed",
            "exception": None,
            "semantic": False,
        },
    ], result


class _Report:
    def __init__(self, case: MutationCase) -> None:
        self.case = case
        self.reports: list[dict[str, Any]] = []
        self.collection_errors = 0
        self.internal_errors = 0

    def pytest_collectreport(self, report: Any) -> None:
        self.collection_errors += int(report.failed)

    def pytest_internalerror(self, excrepr: Any, excinfo: Any) -> None:
        self.internal_errors += 1

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: Any, call: Any) -> Any:
        outcome = yield
        report = outcome.get_result()
        filename, test = report.nodeid.split("::", 1)
        self.reports.append(
            {
                "node": f"{Path(filename).name}::{test}",
                "phase": report.when,
                "outcome": report.outcome,
                "exception": None
                if call.excinfo is None
                else call.excinfo.type.__name__,
                "semantic": bool(
                    report.failed and self.case.marker in str(report.longrepr)
                ),
            }
        )


def _main() -> int:
    name, directory, result_file = sys.argv[1:]
    case = next(case for case in CASES if case.name == name)
    extension = Path(directory)
    sys.path[:0] = [str(extension), str(extension / "tests")]
    plugin = _Report(case)
    exit_code = pytest.main(
        [
            "-n",
            "0",
            "-q",
            "--tb=short",
            "--show-capture=no",
            "--rootdir",
            str(extension),
            "--confcutdir",
            str(extension / "tests"),
            "-c",
            str(extension / "pyproject.toml"),
            str(extension / "tests" / case.node),
        ],
        plugins=[plugin],
    )
    Path(result_file).write_text(
        json.dumps(
            {
                "pytest_exit": int(exit_code),
                "reports": plugin.reports,
                "collection_errors": plugin.collection_errors,
                "internal_errors": plugin.internal_errors,
            }
        ),
        encoding="utf-8",
    )
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(_main())
