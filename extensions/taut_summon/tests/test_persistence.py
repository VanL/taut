"""Summon participation in composite Taut persistence I/O."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from simplebroker import Queue
from taut_summon import _state

from taut import TautClient
from taut._exceptions import TautError

pytestmark = pytest.mark.sqlite_only


def _line(record: dict[str, object]) -> bytes:
    return (
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


def _summon_updated_ts_as_integer(raw: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    active: str | None = None
    payload_start: int | None = None
    for index, line in enumerate(lines):
        record = json.loads(line)
        if active is None and record.get("type") == "component_start":
            active = record["name"]
            payload_start = index + 1
        elif active is not None and record.get("type") == "component_end":
            assert payload_start is not None
            record["sha256"] = hashlib.sha256(
                b"".join(lines[payload_start:index])
            ).hexdigest()
            lines[index] = _line(record)
            active = None
            payload_start = None
        elif active == "taut-summon" and record.get("type") == "session":
            record["updated_ts"] = int(record["updated_ts"])
            lines[index] = _line(record)
        elif active is None and record.get("type") == "end":
            record["sha256"] = hashlib.sha256(b"".join(lines[:index])).hexdigest()
            lines[index] = _line(record)
    return b"".join(lines)


def test_summon_round_trip_keeps_continuity_and_clears_live_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="agent")
    client.join("general")
    member = client.last_created_member
    assert member is not None
    assert member.token is not None
    client.close()

    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        _state.ensure_summon_schema(queue)
        _state.record_session(
            queue,
            member_id=member.member_id,
            token=member.token,
            provider="claude",
            driver_pid=12345,
            driver_start_time="old-process",
            updated_ts=99,
        )
        _state.set_wired(
            queue,
            member_id=member.member_id,
            value=True,
            updated_ts=100,
        )
        _state.claim_name(
            queue,
            name="transient",
            provider="claude",
            driver_pid=12345,
            driver_start_time="old-process",
            claimed_ts=101,
        )
    finally:
        queue.close()

    dump_path = tmp_path / "backup.taut.jsonl"
    report = TautClient.dump(output=dump_path, db_path=source)
    assert [part.name for part in report.components] == [
        "simplebroker",
        "taut-core",
        "taut-summon",
    ]
    assert report.components[-1].records == 1
    session_record = next(
        record
        for record in map(json.loads, dump_path.read_text().splitlines())
        if record.get("type") == "session"
    )
    assert session_record["updated_ts"] == "0000000000000000100"
    assert "provider_session_id" not in session_record

    destination = tmp_path / "destination.db"
    TautClient.load(input_path=dump_path, db_path=destination)
    restored_queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(destination))
    try:
        restored = _state.get_session(restored_queue, member.member_id)
        assert restored is not None
        assert restored["token"] == member.token
        assert restored["provider_session_id"] is None
        assert restored["wired"] is True
        assert restored["updated_ts"] == 100
        assert restored["driver_pid"] is None
        assert restored["driver_start_time"] is None
        assert (
            _state.get_claim(
                restored_queue,
                name="transient",
                provider="claude",
            )
            is None
        )
    finally:
        restored_queue.close()

    integer_dump = tmp_path / "integer-token-backup.taut.jsonl"
    integer_dump.write_bytes(_summon_updated_ts_as_integer(dump_path.read_bytes()))
    integer_destination = tmp_path / "integer-destination.db"
    TautClient.load(input_path=integer_dump, db_path=integer_destination)
    integer_queue = Queue(
        _state.LEDGER_QUEUE_NAME,
        db_path=str(integer_destination),
    )
    try:
        integer_restored = _state.get_session(integer_queue, member.member_id)
        assert integer_restored is not None
        assert integer_restored["updated_ts"] == 100
        assert isinstance(integer_restored["updated_ts"], int)
    finally:
        integer_queue.close()


def test_summon_persistence_v2_manifest_and_dump_omit_provider_session_id(
    tmp_path: Path,
) -> None:
    from taut_summon.persistence import create_component
    from taut_summon.persistence_manifest import summon

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="agent")
    try:
        client.join("general")
        member = client.last_created_member
        assert member is not None and member.token is not None
    finally:
        client.close()
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        _state.ensure_summon_schema(queue)
        _state.record_session(
            queue,
            member_id=member.member_id,
            token=member.token,
            provider="claude",
            updated_ts=1,
        )
        records = create_component().dump_records(queue)
    finally:
        queue.close()

    assert summon.component_api_version == 1
    assert summon.write_version == 2
    assert summon.load_versions == frozenset({1, 2})
    assert len(records) == 1
    assert set(records[0]) == {
        "type",
        "member_id",
        "token",
        "provider",
        "wired",
        "updated_ts",
    }
    assert "provider_session_id" not in records[0]


def test_summon_persistence_v2_loads_exact_shape_with_null_physical_session(
    tmp_path: Path,
) -> None:
    from taut_summon.persistence import create_component

    destination = tmp_path / "destination.db"
    TautClient.init(db_path=destination)
    client = TautClient(db_path=destination, as_name="agent")
    try:
        client.join("general")
        member = client.last_created_member
        assert member is not None and member.token is not None
    finally:
        client.close()
    record = {
        "type": "session",
        "member_id": member.member_id,
        "token": member.token,
        "provider": "claude",
        "wired": True,
        "updated_ts": "0000000000000000001",
    }
    component = create_component()
    component.validate_records(
        2, [record], core_member_ids=frozenset({member.member_id})
    )
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(destination))
    try:
        component.ensure_schema(queue)
        with queue.sidecar(transaction=True) as session:
            component.load_records(session, [record])
        restored = _state.get_session(queue, member.member_id)
    finally:
        queue.close()

    assert restored is not None
    assert restored["provider_session_id"] is None


def test_summon_persistence_exact_v1_load_discards_provider_session_id(
    tmp_path: Path,
) -> None:
    from taut_summon.persistence import create_component

    destination = tmp_path / "destination.db"
    TautClient.init(db_path=destination)
    client = TautClient(db_path=destination, as_name="agent")
    try:
        client.join("general")
        member = client.last_created_member
        assert member is not None and member.token is not None
    finally:
        client.close()
    released_v1 = {
        "type": "session",
        "member_id": member.member_id,
        "token": member.token,
        "provider": "claude",
        "provider_session_id": "released-session-value",
        "wired": True,
        "updated_ts": "0000000000000000001",
    }
    component = create_component()
    component.validate_records(
        1, [released_v1], core_member_ids=frozenset({member.member_id})
    )
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(destination))
    try:
        component.ensure_schema(queue)
        with queue.sidecar(transaction=True) as session:
            component.load_records(session, [released_v1])
        restored = _state.get_session(queue, member.member_id)
        redumped = component.dump_records(queue)
    finally:
        queue.close()

    assert restored is not None
    assert restored["provider_session_id"] is None
    assert len(redumped) == 1
    assert "provider_session_id" not in redumped[0]


@pytest.mark.parametrize(
    "updated_ts",
    [
        True,
        1.5,
        1e18,
        "100",
        " 0000000000000000100",
        "٠" * 16 + "١٠٠",
        -1,
    ],
    ids=[
        "boolean",
        "float",
        "exponent",
        "malformed-string",
        "whitespace-string",
        "non-ascii-digits",
        "out-of-range",
    ],
)
def test_summon_persistence_rejects_non_exact_timestamp_representations(
    updated_ts: object,
) -> None:
    from taut_summon.persistence import create_component

    member_id = "m_fixture"
    record = {
        "type": "session",
        "member_id": member_id,
        "token": "token",
        "provider": "claude",
        "provider_session_id": None,
        "wired": False,
        "updated_ts": updated_ts,
    }

    with pytest.raises(ValueError, match="invalid taut-summon session record"):
        create_component().validate_records(
            1,
            [record],
            core_member_ids=frozenset({member_id}),
        )


def test_existing_empty_summon_schema_emits_zero_record_component(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        _state.ensure_summon_schema(queue)
    finally:
        queue.close()

    report = TautClient.dump(
        output=tmp_path / "backup.taut.jsonl",
        db_path=source,
    )

    summon_components = [
        component for component in report.components if component.name == "taut-summon"
    ]
    assert len(summon_components) == 1
    assert summon_components[0].records == 0


def test_doctor_passively_validates_active_summon_schema(tmp_path: Path) -> None:
    """[DOCT-4.5] Current active Summon state is readable and unchanged."""

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        _state.ensure_summon_schema(queue)
        before = _state.get_summon_schema_version(queue)
    finally:
        queue.close()

    report = TautClient.doctor(db_path=source)

    extension = next(
        check for check in report.checks if check.name == "extension_state"
    )
    assert extension.status == "pass"
    assert extension.data == {
        "active": ["taut-summon"],
        "installed": ["taut-summon"],
        "records": {"taut-summon": 0},
    }
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        assert _state.get_summon_schema_version(queue) == before
    finally:
        queue.close()


def test_doctor_reports_incompatible_summon_schema_without_migrating(
    tmp_path: Path,
) -> None:
    """[DOCT-4.5] Live-schema rejection is a contained finding."""

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        _state.ensure_summon_schema(queue)
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_meta SET value = ? WHERE key = ?",
                ("99", _state.SUMMON_SCHEMA_VERSION_KEY),
            )
    finally:
        queue.close()

    report = TautClient.doctor(db_path=source)

    extension = next(
        check for check in report.checks if check.name == "extension_state"
    )
    assert extension.status == "fail"
    assert extension.data["active"] == ["taut-summon"]
    assert extension.data["records"] is None
    assert "upgrade taut-summon" in extension.detail
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        assert _state.get_summon_schema_version(queue) == 99
    finally:
        queue.close()


def test_doctor_reports_missing_summon_table_as_compatibility_finding(
    tmp_path: Path,
) -> None:
    """[PIO-8.2] Normal passive validation proves required table readability."""

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        _state.ensure_summon_schema(queue)
    finally:
        queue.close()
    with sqlite3.connect(source) as connection:
        connection.execute("DROP TABLE taut_summon_sessions")

    report = TautClient.doctor(db_path=source)

    extension = next(
        check for check in report.checks if check.name == "extension_state"
    )
    assert extension.status == "fail"
    assert extension.data["records"] is None
    assert "upgrade taut-summon" in extension.detail
    with sqlite3.connect(source) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'taut_summon_sessions'"
            ).fetchone()
            is None
        )


def test_doctor_unknown_metadata_with_active_summon_has_null_records(
    tmp_path: Path,
) -> None:
    """[DOCT-3.2] Unobserved active record counts are null, never invented."""

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        _state.ensure_summon_schema(queue)
        with queue.sidecar(transaction=True) as session:
            session.run(
                "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
                ("unknown_extension_schema", "1"),
            )
    finally:
        queue.close()

    report = TautClient.doctor(db_path=source)

    extension = next(
        check for check in report.checks if check.name == "extension_state"
    )
    assert extension.status == "fail"
    assert extension.data == {
        "active": ["taut-summon"],
        "installed": ["taut-summon"],
        "records": None,
    }


def test_transient_summon_claim_makes_load_destination_nonfresh(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    source_queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        _state.ensure_summon_schema(source_queue)
    finally:
        source_queue.close()
    dump_path = tmp_path / "backup.taut.jsonl"
    TautClient.dump(output=dump_path, db_path=source)

    destination = tmp_path / "destination.db"
    TautClient.init(db_path=destination)
    destination_queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(destination))
    try:
        _state.ensure_summon_schema(destination_queue)
        _state.claim_name(
            destination_queue,
            name="transient",
            provider="claude",
            driver_pid=12345,
            driver_start_time="old-process",
            claimed_ts=1,
        )
    finally:
        destination_queue.close()

    with pytest.raises(TautError, match="destination is not fresh"):
        TautClient.load(input_path=dump_path, db_path=destination)


def test_unrepresented_empty_summon_schema_makes_destination_nonfresh(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    dump_path = tmp_path / "core-only.taut.jsonl"
    report = TautClient.dump(output=dump_path, db_path=source)
    assert [part.name for part in report.components] == [
        "simplebroker",
        "taut-core",
    ]

    destination = tmp_path / "destination.db"
    TautClient.init(db_path=destination)
    destination_queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(destination))
    try:
        _state.ensure_summon_schema(destination_queue)
        assert _state.persistence_records(destination_queue) == []
    finally:
        destination_queue.close()

    with pytest.raises(TautError, match="destination is not fresh"):
        TautClient.load(input_path=dump_path, db_path=destination)


def test_missing_summon_importer_fails_preflight_before_destination_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut.persistence._operations as operations

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(source))
    try:
        _state.ensure_summon_schema(queue)
    finally:
        queue.close()
    dump_path = tmp_path / "backup.taut.jsonl"
    TautClient.dump(output=dump_path, db_path=source)
    monkeypatch.setattr(operations, "discover_components", lambda: ())
    destination = tmp_path / "must-not-exist.db"

    with pytest.raises(TautError, match="unsupported component 'taut-summon'"):
        TautClient.load(input_path=dump_path, db_path=destination)

    assert not destination.exists()
