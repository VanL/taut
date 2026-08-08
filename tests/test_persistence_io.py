"""Public persistence I/O behavior.

Spec references:
- docs/specs/08-persistence-io.md [PIO-3.2], [PIO-4], [PIO-7.1]
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.sqlite_only


def _line(record: dict[str, object]) -> bytes:
    return (
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _empty_dump_bytes() -> bytes:
    header = _line(
        {
            "components": [
                {"name": "simplebroker", "version": 1},
                {"name": "taut-core", "version": 1},
            ],
            "format": "taut-dump",
            "type": "header",
            "version": 1,
        }
    )
    simplebroker_payload = _line(
        {
            "backend": "sqlite",
            "format": "simplebroker-dump",
            "last_ts": 0,
            "type": "header",
            "version": 1,
        }
    )
    simplebroker = b"".join(
        (
            _line(
                {
                    "name": "simplebroker",
                    "type": "component_start",
                    "version": 1,
                }
            ),
            simplebroker_payload,
            _line(
                {
                    "name": "simplebroker",
                    "records": 1,
                    "sha256": hashlib.sha256(simplebroker_payload).hexdigest(),
                    "type": "component_end",
                }
            ),
        )
    )
    core = b"".join(
        (
            _line({"name": "taut-core", "type": "component_start", "version": 1}),
            _line(
                {
                    "name": "taut-core",
                    "records": 0,
                    "sha256": hashlib.sha256(b"").hexdigest(),
                    "type": "component_end",
                }
            ),
        )
    )
    prefix = header + simplebroker + core
    return prefix + _line(
        {
            "components": 2,
            "records": 1,
            "sha256": hashlib.sha256(prefix).hexdigest(),
            "type": "end",
        }
    )


def test_load_dry_run_validates_an_empty_dump_without_opening_destination(
    tmp_path: Path,
) -> None:
    from taut import TautClient

    input_path = tmp_path / "empty.taut.jsonl"
    input_path.write_bytes(_empty_dump_bytes())
    destination = tmp_path / "must-not-exist.db"

    report = TautClient.load(
        input_path=input_path,
        db_path=destination,
        dry_run=True,
    )

    assert report.path == str(input_path)
    assert report.format == "taut-dump"
    assert report.version == 1
    assert [(part.name, part.version, part.records) for part in report.components] == [
        ("simplebroker", 1, 1),
        ("taut-core", 1, 0),
    ]
    assert report.queues == 0
    assert report.messages == 0
    assert report.dry_run is True
    assert report.destination_checked is False
    assert report.applied is False
    assert not destination.exists()


def test_dump_writes_an_owner_only_empty_composite_that_preflights(
    tmp_path: Path,
) -> None:
    from taut import TautClient

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    output = tmp_path / "backup.taut.jsonl"

    dumped = TautClient.dump(output=output, db_path=source)
    checked = TautClient.load(
        input_path=output,
        db_path=tmp_path / "unused.db",
        dry_run=True,
    )

    assert dumped.path == str(output)
    assert dumped.format == checked.format == "taut-dump"
    assert dumped.version == checked.version == 1
    assert dumped.components == checked.components
    assert dumped.queues == checked.queues == 0
    assert dumped.messages == checked.messages == 0
    assert dumped.omitted_claimed_messages == 0
    assert output.stat().st_mode & 0o777 == 0o600


def test_sqlite_round_trip_preserves_core_state_and_exact_message_ids(
    tmp_path: Path,
) -> None:
    from taut import TautClient

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    writer = TautClient(db_path=source, as_name="van")
    writer.join("general")
    writer_member = writer.last_created_member
    assert writer_member is not None
    assert writer_member.token is not None
    original_topic = writer.set_channel_topic(
        "general",
        "Persistence keeps the current topic",
    )
    reader = TautClient(db_path=source, as_name="reader")
    reader.join("general")
    reader_member = reader.last_created_member
    assert reader_member is not None
    assert reader_member.token is not None
    caught_up = writer.say("general", "cursor stops here")
    assert [message.ts for message in reader.read("general")] == [caught_up.ts]
    original = writer.say("general", "@reader héllo from source")
    before = next(
        thread
        for thread in reader.list_threads(all_threads=True)
        if thread.name == "general"
    )
    assert (before.unread, before.unread_count) == (True, 1)
    reader.close()
    writer.close()

    dump_path = tmp_path / "backup.taut.jsonl"
    TautClient.dump(output=dump_path, db_path=source)
    destination = tmp_path / "restored.db"

    report = TautClient.load(input_path=dump_path, db_path=destination)

    assert report.applied is True
    assert report.destination_checked is True
    from simplebroker import Queue

    from taut._constants import META_QUEUE_NAME
    from taut.state import SqlSidecarTautState, dialect_for_taut_target

    restored_meta = Queue(META_QUEUE_NAME, db_path=str(destination))
    try:
        restored_state = SqlSidecarTautState(
            restored_meta,
            dialect_for_taut_target(str(destination)),
        )
        restored_writer = restored_state.get_member(writer_member.member_id)
        assert restored_writer is not None
        assert restored_writer["anchor_pid"] is None
        assert restored_writer["anchor_start_time"] is None
    finally:
        restored_meta.close()

    restored = TautClient(db_path=destination, token=writer_member.token)
    assert restored.get_channel("general") == original_topic
    messages = restored.log("general")
    assert (messages[-1].ts, messages[-1].text) == (
        original.ts,
        "@reader héllo from source",
    )
    assert [hit.text for hit in restored.search("héllo")] == [
        "@reader héllo from source"
    ]
    restored.close()

    restored_reader = TautClient(db_path=destination, token=reader_member.token)
    after = next(
        thread
        for thread in restored_reader.list_threads(all_threads=True)
        if thread.name == "general"
    )
    assert (after.unread, after.unread_count) == (True, 1)
    assert [message.ts for message in restored_reader.read_unread("general")] == [
        original.ts
    ]
    notifications = restored_reader.inbox()
    assert [
        (notice.type, notice.thread, notice.message_ts) for notice in notifications
    ] == [("mention", "general", original.ts)]
    restored_reader.close()

    restored = TautClient(db_path=destination, token=writer_member.token)
    later = restored.say("general", "after restore")
    assert later.ts > original.ts
    restored.close()


def test_dump_selects_only_registered_pending_messages_and_counts_claimed(
    tmp_path: Path,
) -> None:
    from simplebroker import Queue, open_broker

    from taut import TautClient

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    writer = TautClient(db_path=source, as_name="van")
    writer.join("general")
    selected = Queue("general", db_path=str(source))
    assert selected.read_one() is not None  # channel-creation notice
    writer.say("general", "claimed and omitted")
    assert selected.read_one() is not None
    pending = writer.say("general", "pending and retained")
    writer.close()
    selected.close()

    foreign = Queue("foreign.queue", db_path=str(source))
    foreign.write("not Taut state")
    foreign.close()
    control = Queue("sys.ctl_fixture", db_path=str(source))
    control.write("transient extension control")
    control.close()
    with open_broker(str(source)) as broker:
        broker.add_alias("legacy-general", "general")

    dump_path = tmp_path / "backup.taut.jsonl"
    report = TautClient.dump(output=dump_path, db_path=source)

    records = [json.loads(line) for line in dump_path.read_text().splitlines()]
    messages = [record for record in records if record.get("type") == "message"]
    assert len(messages) == 1
    assert messages[0]["id"] == pending.ts
    assert messages[0]["queue"] == "general"
    assert json.loads(messages[0]["body"])["text"] == "pending and retained"
    assert not any(record.get("type") == "alias" for record in records)
    assert report.queues == 2  # channel plus the registered empty notification inbox
    assert report.messages == 1
    assert report.omitted_claimed_messages == 2


def test_load_guard_blocks_init_client_and_dump_with_recovery_diagnostic(
    tmp_path: Path,
) -> None:
    from simplebroker import Queue

    from taut import TautClient
    from taut._exceptions import TautError
    from taut.state import SqlSidecarTautState, dialect_for_taut_target

    destination = tmp_path / "guarded.db"
    TautClient.init(db_path=destination)
    queue = Queue("taut_meta", db_path=str(destination))
    try:
        state = SqlSidecarTautState(
            queue,
            dialect_for_taut_target(str(destination)),
        )
        state.acquire_load_guard()
    finally:
        queue.close()

    diagnostic = "load incomplete; recreate the target"
    with pytest.raises(TautError, match=diagnostic):
        TautClient.init(db_path=destination)
    with pytest.raises(TautError, match=diagnostic):
        TautClient(db_path=destination, as_name="van")
    with pytest.raises(TautError, match=diagnostic):
        TautClient.dump(output=tmp_path / "blocked.dump", db_path=destination)


def test_round_trip_fires_every_core_logical_record_type(tmp_path: Path) -> None:
    from taut import TautClient

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="van")
    client.join("before")
    member = client.last_created_member
    assert member is not None
    message = client.say("before", "rename fixture")
    client._state.add_member_alias(
        member_id=member.member_id,
        alias="operator",
        created_ts=message.ts,
    )
    client._state.add_identity_claim(
        claim_hash="ic_" + "a" * 52,
        member_id=member.member_id,
        claim_kind="fixture",
        host_id="host",
        host_label="host",
        evidence={"source": "persistence-test"},
        seen_ts=message.ts,
    )
    client.rename_channel("before", "after")
    client.close()

    dump_path = tmp_path / "all-core-records.taut.jsonl"
    TautClient.dump(output=dump_path, db_path=source)
    records = [json.loads(line) for line in dump_path.read_text().splitlines()]
    assert {
        "member",
        "member_alias",
        "identity_claim",
        "thread",
        "membership",
        "channel_rename",
    }.issubset({record.get("type") for record in records})

    destination = tmp_path / "restored.db"
    TautClient.load(input_path=dump_path, db_path=destination)
    restored = TautClient(db_path=destination, as_name="operator")
    assert restored.whoami().member_id == member.member_id
    assert restored.log("after")[-1].text == "rename fixture"
    restored.close()


@pytest.mark.parametrize("failure", ["unknown-meta", "incomplete-rename"])
def test_dump_fails_closed_for_unrepresented_sidecar_authority(
    tmp_path: Path,
    failure: str,
) -> None:
    from simplebroker import Queue

    from taut import TautClient
    from taut._exceptions import TautError

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    queue = Queue("taut_meta", db_path=str(source))
    try:
        with queue.sidecar(transaction=True) as session:
            if failure == "unknown-meta":
                session.run(
                    "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
                    ("unknown_schema_version", "1"),
                )
            else:
                session.run(
                    """
                    INSERT INTO taut_channel_renames (
                        old_name, new_name, state, affected_json,
                        started_ts, updated_ts
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("old", "new", "moving", "[]", 1, 1),
                )
    finally:
        queue.close()

    expected = (
        "unrecognized durable extension metadata"
        if failure == "unknown-meta"
        else "incomplete channel rename"
    )
    with pytest.raises(TautError, match=expected):
        TautClient.dump(output=tmp_path / "must-not-exist.dump", db_path=source)
    assert not (tmp_path / "must-not-exist.dump").exists()
