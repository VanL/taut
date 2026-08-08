"""Summon participation in composite Taut persistence I/O."""

from __future__ import annotations

from pathlib import Path

import pytest
from simplebroker import Queue
from taut_summon import _state

from taut import TautClient
from taut._exceptions import TautError

pytestmark = pytest.mark.sqlite_only


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
            provider_session_id="provider-session",
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

    destination = tmp_path / "destination.db"
    TautClient.load(input_path=dump_path, db_path=destination)
    restored_queue = Queue(_state.LEDGER_QUEUE_NAME, db_path=str(destination))
    try:
        restored = _state.get_session(restored_queue, member.member_id)
        assert restored is not None
        assert restored["token"] == member.token
        assert restored["provider_session_id"] == "provider-session"
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

    assert report.components[-1].name == "taut-summon"
    assert report.components[-1].records == 0


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
