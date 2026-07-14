from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests import conftest as root_conftest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.sqlite_only

COLLECTION_REPORTER = """
import json
import sys

import pytest


class Reporter:
    def pytest_collection_finish(self, session):
        print("TAUT_COLLECTED=" + json.dumps([
            {
                "nodeid": item.nodeid,
                "uses_fixture": "installed_command_fixture" in item.fixturenames,
                "installed_marker": item.get_closest_marker("installed_wheel")
                is not None,
                "slow_marker": item.get_closest_marker("slow") is not None,
                "xdist_groups": [
                    list(mark.args) for mark in item.iter_markers("xdist_group")
                ],
            }
            for item in session.items
        ]))


raise SystemExit(pytest.main(sys.argv[1:], plugins=[Reporter()]))
"""


def _collection_records(
    *, marker: str, path: str = "tests"
) -> tuple[dict[str, Any], ...]:
    env = os.environ.copy()
    env["PYTEST_ADDOPTS"] = ""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            COLLECTION_REPORTER,
            "--collect-only",
            "-q",
            "--strict-markers",
            "-m",
            marker,
            path,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert completed.returncode in (0, 5), completed.stdout + completed.stderr
    report = next(
        line.removeprefix("TAUT_COLLECTED=")
        for line in completed.stdout.splitlines()
        if line.startswith("TAUT_COLLECTED=")
    )
    return tuple(json.loads(report))


def _collected_nodeids(*, marker: str, path: str = "tests") -> tuple[str, ...]:
    return tuple(
        record["nodeid"] for record in _collection_records(marker=marker, path=path)
    )


def test_installed_environment_uses_the_matrix_interpreter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(root_conftest.subprocess, "run", run)
    root_conftest._install_command_fixture_environment(
        "uv",
        tmp_path,
        tmp_path / "core.whl",
        tmp_path / "plugin.whl",
    )

    assert calls[0][:4] == [
        "uv",
        "venv",
        "--python",
        sys.executable,
    ]


def test_fixture_consumers_are_marked_before_marker_deselection() -> None:
    path = "tests/test_lazy_imports.py"

    prior = set(_collected_nodeids(marker="not slow", path=path))
    broad = set(
        _collected_nodeids(marker="not slow and not installed_wheel", path=path)
    )
    installed = set(
        _collected_nodeids(marker="not slow and installed_wheel", path=path)
    )

    assert installed
    assert broad.isdisjoint(installed)
    assert broad | installed == prior


def test_root_selectors_partition_prior_collection_without_duplicates() -> None:
    records = _collection_records(marker="")
    unfiltered_items = tuple(record["nodeid"] for record in records)
    unfiltered = set(unfiltered_items)
    prior = {record["nodeid"] for record in records if not record["slow_marker"]}
    broad = {
        record["nodeid"]
        for record in records
        if not record["slow_marker"] and not record["installed_marker"]
    }
    installed = {
        record["nodeid"]
        for record in records
        if not record["slow_marker"] and record["installed_marker"]
    }

    assert len(unfiltered_items) == len(unfiltered)
    assert installed
    assert broad.isdisjoint(installed)
    assert broad | installed == prior

    fixture_consumers = {
        record["nodeid"] for record in records if record["uses_fixture"]
    }
    derived_marker_items = {
        record["nodeid"] for record in records if record["installed_marker"]
    }
    expected_non_slow_consumers = {
        record["nodeid"]
        for record in records
        if record["uses_fixture"] and not record["slow_marker"]
    }
    assert derived_marker_items == fixture_consumers
    assert expected_non_slow_consumers == installed
    assert fixture_consumers
    for record in records:
        if record["uses_fixture"]:
            assert record["xdist_groups"] == [["installed-wheel"]]
