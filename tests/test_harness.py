from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import tests.conftest as harness

pytestmark = pytest.mark.sqlite_only


class _FakeItem:
    def __init__(
        self,
        *,
        nodeid: str = "tests/test_new.py::test_new",
        path: Path = Path("tests/test_new.py"),
        markers: set[str] | None = None,
        xdist_markers: tuple[object, ...] = (),
    ) -> None:
        self.nodeid = nodeid
        self.path = path
        self._markers = markers or set()
        self._xdist_markers = xdist_markers

    def get_closest_marker(self, name: str) -> object | None:
        if name in self._markers:
            return object()
        return None

    def iter_markers(self, name: str) -> tuple[object, ...]:
        return self._xdist_markers if name == "xdist_group" else ()


class _FakeMark:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs


def test_source_shard_parser_is_opt_in_and_rejects_invalid_domains() -> None:
    assert harness._parse_source_shard(None) is None
    assert harness._parse_source_shard("") is None
    assert harness._parse_source_shard("full") is None
    assert harness._parse_source_shard("0/4") == (0, 4)
    assert harness._parse_source_shard("3/4") == (3, 4)

    for invalid in ("0/1", "4/4", "-1/4", "one/four", "0/04", " 0/4"):
        with pytest.raises(pytest.UsageError, match="--taut-source-shard"):
            harness._parse_source_shard(invalid)


def test_source_shard_key_matches_complete_xdist_group_identity() -> None:
    item = _FakeItem(
        xdist_markers=(
            _FakeMark("beta"),
            _FakeMark(name="alpha"),
            _FakeMark("alpha"),
        )
    )

    assert harness._effective_xdist_group(item) == "alpha_beta"
    assert harness._source_shard_key(item) == "group\0alpha_beta"

    ungrouped = _FakeItem(nodeid="tests/test_new.py::test_new")
    assert harness._effective_xdist_group(ungrouped) is None
    assert harness._source_shard_key(ungrouped) == ("node\0tests/test_new.py::test_new")


def test_source_shard_assignment_has_fixed_cross_process_vectors() -> None:
    assert (
        harness._source_shard_index(
            "node\0tests/test_cli.py::test_cli_json_join_say_log", 4
        )
        == 3
    )
    assert harness._source_shard_index("group\0alpha_beta", 4) == 2
    assert harness._source_shard_index("group\0installed-wheel", 4) == 2

    code = (
        "from tests.conftest import _source_shard_index; "
        "print(_source_shard_index('group\\0alpha_beta', 4))"
    )
    outputs = []
    for seed in ("1", "987654321"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=harness.PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        outputs.append(completed.stdout.strip())
    assert outputs == ["2", "2"]


def _collect_source_factor_records(
    paths: tuple[Path, ...],
    *,
    shard: str,
) -> tuple[dict[str, str | None], ...]:
    reporter = """
import json
import sys

import pytest
import tests.conftest as harness


class Reporter:
    def pytest_collection_finish(self, session):
        records = [
            {
                "nodeid": item.nodeid,
                "group": harness._effective_xdist_group(item),
            }
            for item in session.items
        ]
        print("TAUT_FACTOR_RECORDS=" + json.dumps(records, sort_keys=True))


raise SystemExit(pytest.main(sys.argv[1:], plugins=[harness, Reporter()]))
"""
    env = os.environ.copy()
    env["PYTEST_ADDOPTS"] = ""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            reporter,
            "-c",
            str(harness.PROJECT_ROOT / "pyproject.toml"),
            f"{harness.SOURCE_SHARD_OPTION}={shard}",
            "--collect-only",
            "-q",
            *(str(path) for path in paths),
        ],
        cwd=harness.PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    prefix = "TAUT_FACTOR_RECORDS="
    payload = next(
        line.removeprefix(prefix)
        for line in completed.stdout.splitlines()
        if line.startswith(prefix)
    )
    records = json.loads(payload)
    assert isinstance(records, list)
    return tuple(records)


def test_source_factor_real_collection_is_complete_disjoint_and_group_safe(
    tmp_path: Path,
) -> None:
    grouped = tmp_path / "test_grouped.py"
    grouped.write_text(
        """
import pytest

pytestmark = [pytest.mark.sqlite_only, pytest.mark.xdist_group("module")]


@pytest.mark.xdist_group(name="keyword")
def test_keyword():
    pass


@pytest.mark.xdist_group()
def test_default():
    pass


@pytest.mark.xdist_group("factor-9")
def test_fixed_shard_zero():
    pass


@pytest.mark.xdist_group("factor-6")
def test_fixed_shard_one():
    pass


class TestInherited:
    pytestmark = pytest.mark.xdist_group(name="class")

    @pytest.mark.xdist_group("function")
    def test_multiple(self):
        pass

    @pytest.mark.xdist_group("function")
    def test_same_effective_identity(self):
        pass


def test_dynamic_installed_group(installed_command_fixture):
    pass
""",
        encoding="utf-8",
    )
    plain = tmp_path / "test_plain.py"
    plain.write_text(
        """
import pytest

pytestmark = pytest.mark.sqlite_only


def test_plain_one():
    pass


def test_plain_two():
    pass
""",
        encoding="utf-8",
    )
    paths = (grouped, plain)

    complete = _collect_source_factor_records(paths, shard="full")
    shards = tuple(
        _collect_source_factor_records(paths, shard=f"{index}/4") for index in range(4)
    )
    complete_ids = {record["nodeid"] for record in complete}
    shard_ids = [{record["nodeid"] for record in shard} for shard in shards]

    assert complete_ids
    assert all(shard_ids)
    assert set().union(*shard_ids) == complete_ids
    for index, left in enumerate(shard_ids):
        for right in shard_ids[index + 1 :]:
            assert left.isdisjoint(right)

    group_destinations: dict[str, set[int]] = {}
    for index, shard in enumerate(shards):
        for record in shard:
            group = record["group"]
            if group is not None:
                group_destinations.setdefault(group, set()).add(index)
    assert group_destinations
    assert all(len(destinations) == 1 for destinations in group_destinations.values())
    assert any("class_function_module" == group for group in group_destinations)
    assert any("installed-wheel_module" == group for group in group_destinations)


def test_source_factor_option_does_not_leak_into_nested_pytest(
    tmp_path: Path,
) -> None:
    child = tmp_path / "test_nested_child.py"
    child.write_text(
        """
import pytest

pytestmark = pytest.mark.sqlite_only


def test_child_one():
    pass


def test_child_two():
    pass
""",
        encoding="utf-8",
    )
    parent = tmp_path / "test_sharded_parent.py"
    parent.write_text(
        f"""
import os
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.sqlite_only, pytest.mark.xdist_group("nested-parent")]


def test_nested_collection_defaults_to_full():
    env = os.environ.copy()
    env["PYTEST_ADDOPTS"] = ""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-o",
            "addopts=",
            "-vv",
            "-c",
            {str(harness.PROJECT_ROOT / "pyproject.toml")!r},
            {str(child)!r},
        ],
        cwd={str(harness.PROJECT_ROOT)!r},
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "collected 2 items" in completed.stdout
""",
        encoding="utf-8",
    )
    shard = harness._source_shard_index("group\0nested-parent", 4)
    env = os.environ.copy()
    env["PYTEST_ADDOPTS"] = ""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.conftest",
            f"{harness.SOURCE_SHARD_OPTION}={shard}/4",
            "-q",
            "-n",
            "0",
            "-c",
            str(harness.PROJECT_ROOT / "pyproject.toml"),
            str(parent),
        ],
        cwd=harness.PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_run_cli_writes_pg_config_with_worker_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BROKER_TEST_BACKEND", "postgres")
    monkeypatch.setenv(
        "SIMPLEBROKER_PG_TEST_DSN",
        "postgresql://postgres:postgres@127.0.0.1:5432/taut_test",
    )
    monkeypatch.setenv("SIMPLEBROKER_PG_TEST_SCHEMA", "taut_pytest_gw0")

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert cmd[:3] == [harness.sys.executable, "-m", "taut"]
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)

    rc, out, err = harness.run_cli("init", cwd=tmp_path)

    assert (rc, out, err) == (0, "", "")
    config = (tmp_path / ".taut.toml").read_text(encoding="utf-8")
    assert 'schema = "taut_pytest_gw0"' in config


def test_run_cli_rejects_stdin_and_stdin_bytes_together(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        harness.run_cli("init", cwd=tmp_path, stdin="text", stdin_bytes=b"bytes")


def test_run_cli_stdin_bytes_branch_returns_decoded_str(tmp_path: Path) -> None:
    # Real subprocess: the binary-stdin branch must keep the (int, str, str)
    # return contract even when stdin carries invalid UTF-8.
    rc, out, err = harness.run_cli(
        "--version", cwd=tmp_path, stdin_bytes=b"\xff\xfe not utf-8"
    )

    assert rc == 0
    assert isinstance(out, str) and isinstance(err, str)
    assert out.startswith("taut ")


def test_shared_contract_filenames_require_shared_marker() -> None:
    assert harness._requires_explicit_shared_marker(Path("test_shared_contract.py"))
    assert not harness._requires_explicit_shared_marker(Path("test_client.py"))


def test_collection_requires_explicit_backend_marker() -> None:
    items: Any = [_FakeItem()]

    with pytest.raises(pytest.UsageError, match="has no backend marker"):
        harness.pytest_collection_modifyitems(items)


def test_collection_accepts_explicit_backend_marker() -> None:
    items: Any = [_FakeItem(markers={"sqlite_only"})]

    harness.pytest_collection_modifyitems(items)


def test_collection_requires_shared_marker_for_shared_filenames() -> None:
    items: Any = [
        _FakeItem(
            nodeid="tests/test_shared_new.py::test_new",
            path=Path("tests/test_shared_new.py"),
        )
    ]

    with pytest.raises(pytest.UsageError, match="marked with @pytest.mark.shared"):
        harness.pytest_collection_modifyitems(items)


def test_postgres_schema_for_worker_is_safe() -> None:
    assert harness.postgres_schema_for_worker("gw0") == "taut_pytest_gw0"
    assert harness.postgres_schema_for_worker("Master-1") == "taut_pytest_master_1"
