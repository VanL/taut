from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import sqlite3
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from simplebroker import Queue, open_broker
from simplebroker.ext import DatabaseError

from taut import DoctorCheck, DoctorReport, TautClient, TautError
from taut._constants import META_QUEUE_NAME
from taut.persistence import PersistenceComponentSpec
from taut.persistence._components import RegisteredPersistenceComponent
from taut.search._jobs import CLAIMED_QUEUE_NAME, FAILED_QUEUE_NAME, PENDING_QUEUE_NAME
from tests.conftest import ensure_taut_project_config, run_cli

pytestmark = pytest.mark.sqlite_only


def test_doctor_missing_postgres_plugin_mentions_taut_pg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ensure_taut_project_config(
        tmp_path,
        dsn="postgresql://taut.example/missing_plugin",
        schema="taut_schema",
    )
    monkeypatch.chdir(tmp_path)

    class EmptyEntryPoints:
        def select(self, **_kwargs: object) -> tuple[object, ...]:
            return ()

    monkeypatch.setattr(importlib_metadata, "entry_points", EmptyEntryPoints)

    with pytest.raises(TautError, match="Install taut-pg"):
        TautClient.doctor()


def test_doctor_preserves_taut_error_shape_for_other_resolution_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import taut._maintenance as maintenance

    monkeypatch.chdir(tmp_path)

    def fail_resolution(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("backend resolution failed")

    monkeypatch.setattr(maintenance, "resolve_broker_target", fail_resolution)

    with pytest.raises(TautError, match="backend resolution failed"):
        TautClient.doctor()


def _doctor_check(report: DoctorReport, name: str) -> DoctorCheck:
    return next(check for check in report.checks if check.name == name)


def _write_meta(db_path: Path, key: str, value: str) -> None:
    queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                "INSERT INTO taut_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
    finally:
        queue.close()


def _registered_component(component: Any) -> RegisteredPersistenceComponent:
    return RegisteredPersistenceComponent(
        PersistenceComponentSpec(
            component_api_version=1,
            name="fixture",
            write_version=1,
            load_versions=frozenset({1}),
            schema_keys=frozenset({"fixture_schema"}),
            implementation="tests.test_system_doctor:create_fixture",
        ),
        component,
    )


class _MissingPassiveComponent:
    def dump_records(self, _queue: Queue) -> list[dict[str, Any]]:
        return []

    def validate_records(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def ensure_schema(self, _queue: Queue) -> None:
        pytest.fail("doctor called ensure_schema")

    def is_fresh(self, _queue: Queue) -> bool:
        pytest.fail("doctor called is_fresh")

    def load_records(self, *_args: Any, **_kwargs: Any) -> None:
        pytest.fail("doctor called load_records")


class _InvalidRecordsComponent(_MissingPassiveComponent):
    def validate_live_schema(self, _queue: Queue) -> None:
        return None

    def dump_records(self, _queue: Queue) -> list[dict[str, Any]]:
        return [{"bad": True}]

    def validate_records(self, *_args: Any, **_kwargs: Any) -> None:
        raise ValueError("bad cross-reference")


class _CrashingPassiveComponent(_MissingPassiveComponent):
    def validate_live_schema(self, _queue: Queue) -> None:
        raise RuntimeError("password=hunter2")


def test_doctor_reports_exact_healthy_initialized_workspace(tmp_path: Path) -> None:
    """[DOCT-3] [DOCT-4] A fresh workspace has one complete healthy report."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)

    report = TautClient.doctor(db_path=db_path)

    assert isinstance(report, DoctorReport)
    assert report.db == str(db_path)
    assert report.healthy is True
    assert [check.name for check in report.checks] == [
        "core_schema",
        "load_guard",
        "core_state",
        "broker_state",
        "extension_state",
        "search_work",
        "debug_capture",
    ]
    assert all(isinstance(check, DoctorCheck) for check in report.checks)
    assert [check.status for check in report.checks] == ["pass"] * 7
    assert [check.data for check in report.checks] == [
        {"version": 2},
        {"present": False},
        {
            "aliases": 0,
            "completed_renames": 0,
            "identity_claims": 0,
            "members": 0,
            "memberships": 0,
            "threads": 0,
        },
        {
            "claimed": 0,
            "observed_nonempty_queues": 0,
            "pending": 0,
            "registered_threads": 0,
        },
        {"active": [], "installed": ["taut-summon"], "records": {}},
        {"claimed": 0, "failed": 0, "pending": 0},
        {"enabled": False, "sink": "disabled"},
    ]
    assert all(check.detail and "\n" not in check.detail for check in report.checks)


def test_doctor_cli_json_is_recursive_sorted_and_quiet_preserves_status(
    tmp_path: Path,
) -> None:
    """[DOCT-3.1] [DOCT-3.3] CLI JSON is exact; quiet changes output only."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)

    rc, out, err = run_cli(
        "--db", str(db_path), "system", "doctor", "--json", cwd=tmp_path
    )

    assert rc == 0
    assert err == ""
    payload = json.loads(out)
    assert set(payload) == {"checks", "db", "healthy", "type"}
    assert all(
        set(check) == {"data", "detail", "name", "status"}
        for check in payload["checks"]
    )
    assert payload["type"] == "system_doctor"
    assert payload["healthy"] is True
    assert out == json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    quiet_rc, quiet_out, quiet_err = run_cli(
        "--db", str(db_path), "system", "doctor", "--quiet", cwd=tmp_path
    )
    assert (quiet_rc, quiet_out, quiet_err) == (0, "", "")


def test_doctor_cli_finding_exits_two_with_complete_report(tmp_path: Path) -> None:
    """[DOCT-3.1] A completed target finding uses the scoped exit 2."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
                ("load_guard", "test-guard"),
            )
    finally:
        queue.close()

    rc, out, err = run_cli(
        "--db", str(db_path), "system", "doctor", "--json", cwd=tmp_path
    )

    assert rc == 2
    assert err == ""
    payload = json.loads(out)
    assert payload["healthy"] is False
    assert len(payload["checks"]) == 7
    assert payload["checks"][1]["name"] == "load_guard"
    assert payload["checks"][1]["status"] == "fail"
    quiet_rc, quiet_out, quiet_err = run_cli(
        "--db", str(db_path), "system", "doctor", "--quiet", cwd=tmp_path
    )
    assert (quiet_rc, quiet_out, quiet_err) == (2, "", "")


@pytest.mark.parametrize(
    ("stored", "reported"),
    [("1", 1), ("3", 3), ("not-an-int", None), ("02", None)],
)
def test_doctor_schema_findings_skip_only_dependent_checks(
    tmp_path: Path,
    stored: str,
    reported: int | None,
) -> None:
    """[DOCT-4.1] Incompatible metadata retains fixed nullable shapes."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    _write_meta(db_path, "schema_version", stored)

    report = TautClient.doctor(db_path=db_path)

    assert report.healthy is False
    assert _doctor_check(report, "core_schema").data == {"version": reported}
    assert _doctor_check(report, "core_schema").status == "fail"
    assert _doctor_check(report, "load_guard").data == {"present": False}
    assert _doctor_check(report, "load_guard").status == "pass"
    assert _doctor_check(report, "core_state").status == "skip"
    assert all(
        value is None for value in _doctor_check(report, "core_state").data.values()
    )
    assert _doctor_check(report, "broker_state").status == "skip"
    assert _doctor_check(report, "extension_state").status == "skip"
    assert _doctor_check(report, "search_work").status == "pass"


def test_doctor_required_column_finding_retains_observed_meta(tmp_path: Path) -> None:
    """[DOCT-4.1] Table-shape failure retains version and guard observations."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE taut_membership")
        connection.execute("CREATE TABLE taut_membership (wrong TEXT)")

    report = TautClient.doctor(db_path=db_path)

    assert _doctor_check(report, "core_schema").status == "fail"
    assert _doctor_check(report, "core_schema").data == {"version": 2}
    assert _doctor_check(report, "load_guard").status == "pass"
    assert _doctor_check(report, "load_guard").data == {"present": False}
    assert _doctor_check(report, "core_state").status == "skip"


@pytest.mark.parametrize("stored_meta", ['{"topic":{"text":7}}', "{bad"])
def test_doctor_malformed_channel_metadata_is_core_finding(
    tmp_path: Path,
    stored_meta: str,
) -> None:
    """[DOCT-4.3] Owned topic and JSON corruption never reports healthy."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    client = TautClient(db_path=db_path, as_name="van")
    client.join("general")
    client.close()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE taut_threads SET meta = ? WHERE name = ?",
            (stored_meta, "general"),
        )

    report = TautClient.doctor(db_path=db_path)

    assert _doctor_check(report, "core_state").status == "fail"
    assert report.healthy is False


@pytest.mark.parametrize("corruption", ["name", "membership"])
def test_doctor_rejects_invalid_direct_message_pair(
    tmp_path: Path,
    corruption: str,
) -> None:
    """[DOCT-4.3] Stable DM name and participant memberships stay exact."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    alice = TautClient(db_path=db_path, as_name="alice")
    alice.join("general")
    alice.close()
    bob = TautClient(db_path=db_path, as_name="bob")
    bob.join("general")
    bob.close()
    alice = TautClient(db_path=db_path, as_name="alice")
    message = alice.say("@bob", "hello")
    alice.close()
    with sqlite3.connect(db_path) as connection:
        if corruption == "name":
            fake = "dm.d_aaaaaaaaaaaaaaaaaaaaaaaaaa"
            connection.execute(
                "UPDATE taut_threads SET name = ? WHERE name = ?",
                (fake, message.thread),
            )
            connection.execute(
                "UPDATE taut_membership SET thread = ? WHERE thread = ?",
                (fake, message.thread),
            )
        else:
            connection.execute(
                "DELETE FROM taut_membership WHERE thread = ? AND member_id = "
                "(SELECT MIN(member_id) FROM taut_membership WHERE thread = ?)",
                (message.thread, message.thread),
            )

    report = TautClient.doctor(db_path=db_path)

    assert _doctor_check(report, "core_state").status == "fail"
    assert report.healthy is False


def test_doctor_incomplete_rename_is_core_finding_and_never_resumed(
    tmp_path: Path,
) -> None:
    """[DOCT-4.3] Incomplete rename evidence is reported without repair."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        with queue.sidecar(transaction=True) as session:
            session.run(
                "INSERT INTO taut_channel_renames "
                "(old_name, new_name, state, affected_json, started_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("old", "new", "broker_renamed", "[]", 1, 1),
            )
    finally:
        queue.close()

    report = TautClient.doctor(db_path=db_path)

    core = _doctor_check(report, "core_state")
    assert core.status == "fail"
    assert "taut channel rename old new" in core.detail
    assert all(value is None for value in core.data.values())
    queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        with queue.sidecar() as session:
            rows = list(
                session.run(
                    "SELECT state FROM taut_channel_renames WHERE old_name = ?",
                    ("old",),
                    fetch=True,
                )
            )
        assert rows == [("broker_renamed",)]
    finally:
        queue.close()


def test_doctor_observes_broker_and_exact_search_queue_totals(tmp_path: Path) -> None:
    """[DOCT-4.4] [DOCT-4.6] Public totals are passive and queue-exact."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    client = TautClient(db_path=db_path, as_name="van")
    client.join("general")
    client.say("general", "hello")
    client.close()
    general = Queue("general", db_path=str(db_path))
    try:
        assert general.read() is not None
    finally:
        general.close()
    owned = [
        Queue(name, db_path=str(db_path))
        for name in (PENDING_QUEUE_NAME, CLAIMED_QUEUE_NAME, FAILED_QUEUE_NAME)
    ]
    try:
        owned[0].write("pending")
        owned[0].write("pending-2")
        owned[1].write("claimed")
        owned[2].write("failed")
    finally:
        for queue in owned:
            queue.close()
    with open_broker(str(db_path)) as observed:
        expected = {item.queue: item.total for item in observed.list_queue_stats()}

    report = TautClient.doctor(db_path=db_path)

    broker = _doctor_check(report, "broker_state")
    assert broker.status == "pass"
    registered_threads = broker.data["registered_threads"]
    pending = broker.data["pending"]
    observed_nonempty = broker.data["observed_nonempty_queues"]
    assert isinstance(registered_threads, int) and registered_threads >= 2
    assert isinstance(pending, int) and pending >= 1
    assert isinstance(observed_nonempty, int) and observed_nonempty >= 1
    claimed = broker.data["claimed"]
    assert isinstance(claimed, int) and claimed >= 1
    search = _doctor_check(report, "search_work")
    assert search.status == "fail"
    assert search.data == {
        "claimed": expected[CLAIMED_QUEUE_NAME],
        "failed": expected[FAILED_QUEUE_NAME],
        "pending": expected[PENDING_QUEUE_NAME],
    }


def test_doctor_ignores_foreign_broker_queues_and_search_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[DOCT-4.4] [DOCT-5] Foreign queues pass and provider code is not called."""

    from taut.search import _discovery

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    foreign = Queue("foreign.queue", db_path=str(db_path))
    try:
        foreign.write("foreign")
    finally:
        foreign.close()
    monkeypatch.setattr(
        _discovery,
        "load_search_provider",
        lambda *_args, **_kwargs: pytest.fail("doctor loaded a search provider"),
    )

    report = TautClient.doctor(db_path=db_path)

    broker = _doctor_check(report, "broker_state")
    assert broker.status == "pass"
    assert broker.data == {
        "claimed": 0,
        "observed_nonempty_queues": 0,
        "pending": 0,
        "registered_threads": 0,
    }
    assert _doctor_check(report, "search_work").status == "pass"


def test_doctor_nonexistent_sqlite_target_is_not_created(tmp_path: Path) -> None:
    """[DOCT-2] [DOCT-3.1] Resolution failure raises and writes nothing."""

    missing = tmp_path / "missing.db"

    rc, out, err = run_cli(
        "--db", str(missing), "system", "doctor", "--json", cwd=tmp_path
    )

    assert rc == 1
    assert out == ""
    assert "no taut database found" in err.lower()
    assert not missing.exists()


def test_doctor_opened_schemaless_target_is_complete_finding(tmp_path: Path) -> None:
    """[DOCT-3.1] An opened target without Taut schema is exit 2, not exit 1."""

    db_path = tmp_path / "schemaless.db"
    db_path.touch()

    report = TautClient.doctor(db_path=db_path)

    assert report.healthy is False
    assert _doctor_check(report, "core_schema").status == "fail"
    assert _doctor_check(report, "core_schema").data == {"version": None}
    assert _doctor_check(report, "search_work").status == "pass"


def test_doctor_does_not_initialize_extensions_or_change_logical_state(
    tmp_path: Path,
) -> None:
    """[DOCT-2] Real passive inspection preserves core, broker, and tables."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    state_queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        from taut.state import SQLITE_SQL_DIALECT, SqlSidecarTautState

        state = SqlSidecarTautState(state_queue, SQLITE_SQL_DIALECT)
        before_meta = state.persistence_meta()
        before_records = state.persistence_records()
    finally:
        state_queue.close()
    with open_broker(str(db_path)) as broker:
        before_stats = tuple(
            (item.queue, item.pending, item.claimed, item.total)
            for item in broker.list_queue_stats()
        )
    with sqlite3.connect(db_path) as connection:
        before_tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        )

    TautClient.doctor(db_path=db_path)

    state_queue = Queue(META_QUEUE_NAME, db_path=str(db_path))
    try:
        state = SqlSidecarTautState(state_queue, SQLITE_SQL_DIALECT)
        assert state.persistence_meta() == before_meta
        assert state.persistence_records() == before_records
    finally:
        state_queue.close()
    with open_broker(str(db_path)) as broker:
        after_stats = tuple(
            (item.queue, item.pending, item.claimed, item.total)
            for item in broker.list_queue_stats()
        )
    with sqlite3.connect(db_path) as connection:
        after_tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        )
    assert after_stats == before_stats
    assert after_tables == before_tables
    assert not any(name.startswith("taut_summon") for name in after_tables)


def test_doctor_human_output_is_eight_escaped_lines(tmp_path: Path) -> None:
    """[DOCT-3.3] Human findings cannot inject terminal controls or rows."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    _write_meta(db_path, "foreign\x1b[31m", "1")

    rc, out, err = run_cli("--db", str(db_path), "system", "doctor", cwd=tmp_path)

    assert rc == 2
    assert err == ""
    assert len(out.splitlines()) == 8
    assert out.splitlines()[-1] == "workspace has findings"
    assert "\x1b" not in out
    assert r"\x1b" in out


@pytest.mark.parametrize(
    "component",
    [_MissingPassiveComponent(), _InvalidRecordsComponent()],
    ids=["missing-passive-method", "invalid-records"],
)
def test_doctor_contains_specified_extension_findings_and_forbidden_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    component: object,
) -> None:
    """[DOCT-4.5] Defined contributor failures are findings, never mutation."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    _write_meta(db_path, "fixture_schema", "1")
    monkeypatch.setattr(
        "taut._doctor.discover_components",
        lambda: (_registered_component(component),),
    )

    report = TautClient.doctor(db_path=db_path)

    extension = _doctor_check(report, "extension_state")
    assert extension.status == "fail"
    assert extension.data == {
        "active": ["fixture"],
        "installed": ["fixture"],
        "records": None,
    }


def test_doctor_allows_no_installed_persistence_contributors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[DOCT-4.5] The optional contributor set may be empty."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    monkeypatch.setattr("taut._doctor.discover_components", lambda: ())

    extension = _doctor_check(TautClient.doctor(db_path=db_path), "extension_state")

    assert extension.status == "pass"
    assert extension.data == {"active": [], "installed": [], "records": {}}


def test_doctor_framework_failure_exits_one_without_partial_or_secret_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[DOCT-3.1] Unexpected contributor code aborts the report safely."""

    from taut.commands._dispatch import dispatch
    from taut.commands._registry import CommandRegistry

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    _write_meta(db_path, "fixture_schema", "1")
    monkeypatch.setattr(
        "taut._doctor.discover_components",
        lambda: (_registered_component(_CrashingPassiveComponent()),),
    )
    with pytest.raises(TautError, match="live-schema inspection failed") as raised:
        TautClient.doctor(db_path=db_path)
    assert "hunter2" not in str(raised.value)
    stdout = StringIO()
    stderr = StringIO()

    result = dispatch(
        ["--db", str(db_path), "system", "doctor", "--json"],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""
    assert "hunter2" not in stderr.getvalue()
    assert len(stderr.getvalue().splitlines()) == 1


def test_doctor_database_access_failure_is_sanitized_framework_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[DOCT-2] [DOCT-6] Access failures never become report findings."""

    from taut.state import SqlSidecarTautState

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)

    def fail_access(_state: SqlSidecarTautState) -> dict[str, str]:
        raise DatabaseError("connection failed; password=hunter2")

    monkeypatch.setattr(SqlSidecarTautState, "probe_persistence_meta", fail_access)

    with pytest.raises(TautError, match="could not access") as raised:
        TautClient.doctor(db_path=db_path)
    assert "hunter2" not in str(raised.value)


def test_doctor_accepts_system_globals_after_nested_operation(tmp_path: Path) -> None:
    """[DOCT-3.1] System globals retain their before/after placement contract."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)

    rc, out, err = run_cli(
        "system",
        "doctor",
        "--db",
        str(db_path),
        "--json",
        cwd=tmp_path,
    )

    assert rc == 0
    assert json.loads(out)["type"] == "system_doctor"
    assert err == ""


@pytest.mark.parametrize(
    "args",
    [
        ("--as", "van", "system", "doctor"),
        ("--token", "secret", "system", "doctor"),
        ("--timestamps", "system", "doctor"),
        ("system", "doctor", "--as", "van"),
        ("system", "doctor", "extra"),
    ],
)
def test_doctor_rejects_actor_globals_and_extra_arguments(
    tmp_path: Path,
    args: tuple[str, ...],
) -> None:
    """[DOCT-3.1] Doctor remains actor-free with a closed grammar."""

    db_path = tmp_path / "workspace.db"
    TautClient.init(db_path=db_path)
    expanded = (*args, "--db", str(db_path)) if args[0] == "system" else args

    rc, out, err = run_cli(*expanded, cwd=tmp_path, env={"TAUT_DB": str(db_path)})

    assert rc == 1
    assert out == ""
    assert err
    assert "Traceback" not in err
