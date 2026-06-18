from __future__ import annotations

import subprocess
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
    ) -> None:
        self.nodeid = nodeid
        self.path = path
        self._markers = markers or set()

    def get_closest_marker(self, name: str) -> object | None:
        if name in self._markers:
            return object()
        return None


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
