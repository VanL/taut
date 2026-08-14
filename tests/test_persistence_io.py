"""Public persistence I/O behavior.

Spec references:
- docs/specs/08-persistence-io.md [PIO-3.2], [PIO-4], [PIO-7.1]
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = pytest.mark.sqlite_only


def test_dump_missing_postgres_plugin_mentions_taut_pg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.metadata as importlib_metadata

    from taut import TautClient, TautError
    from tests.conftest import ensure_taut_project_config

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
        TautClient.dump(output=tmp_path / "backup.taut.jsonl")


def test_load_missing_postgres_plugin_mentions_taut_pg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.metadata as importlib_metadata

    from taut import TautClient, TautError
    from tests.conftest import ensure_taut_project_config

    source = tmp_path / "backup.taut.jsonl"
    source.write_bytes(_empty_dump_bytes())
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
        TautClient.load(input_path=source, dry_run=True)


def test_taut_load_has_no_future_skew_force_surface() -> None:
    from taut import TautClient

    assert "force" not in inspect.signature(TautClient.load).parameters


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
            "last_ts": "0000000000000000000",
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


def _rewrite_component_payloads(
    raw: bytes,
    transform: Callable[[str, dict[str, object]], dict[str, object]],
) -> bytes:
    """Rewrite logical payloads and repair both checksum layers."""

    lines = raw.splitlines(keepends=True)
    active: str | None = None
    payload_start: int | None = None
    final_index: int | None = None
    for index, line in enumerate(lines):
        record = json.loads(line)
        assert isinstance(record, dict)
        if active is None and record.get("type") == "component_start":
            active = record["name"]
            assert isinstance(active, str)
            payload_start = index + 1
        elif active is not None and record.get("type") == "component_end":
            assert payload_start is not None
            record["sha256"] = hashlib.sha256(
                b"".join(lines[payload_start:index])
            ).hexdigest()
            lines[index] = _line(record)
            active = None
            payload_start = None
        elif active is not None:
            lines[index] = _line(transform(active, record))
        elif record.get("type") == "end":
            final_index = index
            record["sha256"] = hashlib.sha256(b"".join(lines[:index])).hexdigest()
            lines[index] = _line(record)
    assert final_index == len(lines) - 1
    return b"".join(lines)


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


def test_dump_writes_empty_composite_that_preflights_and_is_owner_only_on_posix(
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
    if os.name == "posix":
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
    assert messages[0]["id"] == str(pending.ts)
    assert messages[0]["queue"] == "general"
    assert json.loads(messages[0]["body"])["text"] == "pending and retained"
    assert not any(record.get("type") == "alias" for record in records)
    assert report.queues == 2  # channel plus the registered empty notification inbox
    assert report.messages == 1
    assert report.omitted_claimed_messages == 2


def test_claimed_header_only_restore_preserves_watermark_floor(tmp_path: Path) -> None:
    from simplebroker import Queue

    from taut import TautClient

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="van")
    client.join("general")
    newest = client.say("general", "newest then claimed")
    client.close()
    queue = Queue("general", db_path=str(source))
    try:
        assert list(queue.read_generator(with_timestamps=True))
    finally:
        queue.close()

    dump_path = tmp_path / "header-only.taut.jsonl"
    report = TautClient.dump(output=dump_path, db_path=source)
    records = [json.loads(line) for line in dump_path.read_text().splitlines()]
    nested_header = next(
        record for record in records if record.get("format") == "simplebroker-dump"
    )
    high_water = int(nested_header["last_ts"])

    assert report.messages == 0
    assert high_water >= newest.ts
    assert not any(record.get("type") == "message" for record in records)

    destination = tmp_path / "restored.db"
    TautClient.load(input_path=dump_path, db_path=destination)
    restored = Queue("general", db_path=str(destination))
    try:
        later = restored.write("after watermark-only restore")
    finally:
        restored.close()
    assert later > high_water


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
    client.reply("before", str(message.ts), "subthread fixture")
    client.set_channel_topic("before", "persistence topic")
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
    core_timestamp_fields = {
        "member": ("created_ts", "last_active_ts"),
        "member_alias": ("created_ts",),
        "identity_claim": ("first_seen_ts", "last_seen_ts"),
        "thread": ("origin_ts", "created_ts"),
        "membership": ("joined_ts", "last_seen_ts"),
        "channel_rename": ("started_ts", "updated_ts"),
    }
    core_records = [
        record for record in records if record.get("type") in core_timestamp_fields
    ]
    for record in core_records:
        kind = record["type"]
        assert isinstance(kind, str)
        for field in core_timestamp_fields[kind]:
            value = record[field]
            if value is not None:
                assert isinstance(value, str)
                assert len(value) == 19
                assert value.isascii() and value.isdecimal()
        if kind == "thread":
            meta = record["meta"]
            if isinstance(meta, dict) and isinstance(meta.get("topic"), dict):
                updated_ts = meta["topic"]["updated_ts"]
                assert isinstance(updated_ts, str)
                assert len(updated_ts) == 19

    destination = tmp_path / "restored.db"
    TautClient.load(input_path=dump_path, db_path=destination)
    restored = TautClient(db_path=destination, as_name="operator")
    assert restored.whoami().member_id == member.member_id
    assert restored.log("after")[-1].text == "rename fixture"
    for record in cast(Any, restored._state).persistence_records():
        kind = record["type"]
        for field in core_timestamp_fields[kind]:
            value = record[field]
            assert value is None or (
                isinstance(value, int) and not isinstance(value, bool)
            )
        if kind == "thread":
            meta = record["meta"]
            if isinstance(meta, dict) and isinstance(meta.get("topic"), dict):
                assert isinstance(meta["topic"]["updated_ts"], int)
    restored.close()


def test_load_accepts_exact_integer_core_tokens_and_normalizes_storage(
    tmp_path: Path,
) -> None:
    from taut import TautClient

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="van")
    client.join("general")
    client.set_channel_topic("general", "integer-token fixture")
    client.say("general", "payload")
    client.close()
    canonical = tmp_path / "canonical.taut.jsonl"
    TautClient.dump(output=canonical, db_path=source)

    timestamp_fields = {
        "member": ("created_ts", "last_active_ts"),
        "member_alias": ("created_ts",),
        "identity_claim": ("first_seen_ts", "last_seen_ts"),
        "thread": ("origin_ts", "created_ts"),
        "membership": ("joined_ts", "last_seen_ts"),
        "channel_rename": ("started_ts", "updated_ts"),
    }

    def integers(component: str, record: dict[str, object]) -> dict[str, object]:
        if component == "taut-core" and record.get("type") in timestamp_fields:
            kind = record["type"]
            assert isinstance(kind, str)
            for field in timestamp_fields[kind]:
                value = record.get(field)
                if isinstance(value, str):
                    record[field] = int(value)
            meta = record.get("meta")
            if isinstance(meta, dict) and isinstance(meta.get("topic"), dict):
                topic = meta["topic"]
                updated_ts = topic.get("updated_ts")
                if isinstance(updated_ts, str):
                    topic["updated_ts"] = int(updated_ts)
        return record

    integer_dump = tmp_path / "integer-tokens.taut.jsonl"
    integer_dump.write_bytes(
        _rewrite_component_payloads(canonical.read_bytes(), integers)
    )
    destination = tmp_path / "restored.db"
    TautClient.load(input_path=integer_dump, db_path=destination)
    restored = TautClient(db_path=destination, as_name="van")
    assert restored.get_channel("general").topic == "integer-token fixture"
    assert all(isinstance(message.ts, int) for message in restored.log("general"))
    assert all(
        value is None or (isinstance(value, int) and not isinstance(value, bool))
        for record in cast(Any, restored._state).persistence_records()
        for field in timestamp_fields[record["type"]]
        for value in (record[field],)
    )
    restored.close()


@pytest.mark.parametrize(
    "invalid",
    [
        pytest.param(True, id="boolean"),
        pytest.param(1.5, id="float"),
        pytest.param(1e18, id="exponent"),
        pytest.param("123", id="malformed-string"),
        pytest.param(" 0000000000000000100", id="whitespace-string"),
        pytest.param("٠" * 16 + "١٠٠", id="non-ascii-digits"),
        pytest.param(-1, id="out-of-range"),
    ],
)
def test_load_rejects_non_exact_core_timestamp_representations(
    tmp_path: Path,
    invalid: object,
) -> None:
    from taut import TautClient, TautError

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="van")
    client.join("general")
    client.close()
    canonical = tmp_path / "canonical.taut.jsonl"
    TautClient.dump(output=canonical, db_path=source)
    replaced = False

    def corrupt(component: str, record: dict[str, object]) -> dict[str, object]:
        nonlocal replaced
        if component == "taut-core" and record.get("type") == "member" and not replaced:
            record["created_ts"] = invalid
            replaced = True
        return record

    malformed = tmp_path / "malformed.taut.jsonl"
    malformed.write_bytes(_rewrite_component_payloads(canonical.read_bytes(), corrupt))
    assert replaced

    with pytest.raises(TautError, match="invalid .*member record"):
        TautClient.load(input_path=malformed, db_path=tmp_path / "destination.db")


@pytest.mark.parametrize(
    "invalid",
    [
        pytest.param(100, id="integer"),
        pytest.param(True, id="boolean"),
        pytest.param(1.5, id="float"),
        pytest.param(1e18, id="exponent"),
        pytest.param("123", id="malformed-string"),
        pytest.param(" 0000000000000000100", id="whitespace-string"),
        pytest.param("٠" * 16 + "١٠٠", id="non-ascii-digits"),
        pytest.param(-1, id="out-of-range"),
    ],
)
@pytest.mark.parametrize(
    ("record_type", "field", "error"),
    [
        pytest.param("header", "last_ts", "invalid SimpleBroker header", id="header"),
        pytest.param("message", "id", "invalid SimpleBroker message", id="message"),
    ],
)
def test_load_rejects_non_exact_nested_broker_timestamp_representations(
    tmp_path: Path,
    invalid: object,
    record_type: str,
    field: str,
    error: str,
) -> None:
    from taut import TautClient, TautError

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="van")
    client.join("general")
    client.close()
    canonical = tmp_path / "canonical.taut.jsonl"
    TautClient.dump(output=canonical, db_path=source)
    replaced = False

    def corrupt(component: str, record: dict[str, object]) -> dict[str, object]:
        nonlocal replaced
        if (
            component == "simplebroker"
            and record.get("type") == record_type
            and not replaced
        ):
            record[field] = invalid
            replaced = True
        return record

    malformed = tmp_path / "malformed.taut.jsonl"
    malformed.write_bytes(_rewrite_component_payloads(canonical.read_bytes(), corrupt))
    assert replaced

    with pytest.raises(TautError, match=error):
        TautClient.load(input_path=malformed, db_path=tmp_path / "destination.db")


def test_load_rejects_broker_message_above_nested_high_water(tmp_path: Path) -> None:
    from taut import TautClient, TautError

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="van")
    client.join("general")
    client.say("general", "payload")
    client.close()
    canonical = tmp_path / "canonical.taut.jsonl"
    TautClient.dump(output=canonical, db_path=source)
    message_id: int | None = None

    def corrupt(component: str, record: dict[str, object]) -> dict[str, object]:
        nonlocal message_id
        if component != "simplebroker":
            return record
        if record.get("type") == "message":
            message_id = int(cast(str, record["id"]))
        elif record.get("type") == "header":
            record["last_ts"] = "0000000000000000000"
        return record

    malformed = tmp_path / "above-high-water.taut.jsonl"
    malformed.write_bytes(_rewrite_component_payloads(canonical.read_bytes(), corrupt))
    assert message_id is not None and message_id > 0

    with pytest.raises(TautError, match="message exceeds SimpleBroker last_ts"):
        TautClient.load(input_path=malformed, db_path=tmp_path / "destination.db")


def test_load_rejects_membership_cursor_above_nested_high_water(tmp_path: Path) -> None:
    from taut import TautClient, TautError

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="van")
    client.join("general")
    client.close()
    canonical = tmp_path / "canonical.taut.jsonl"
    TautClient.dump(output=canonical, db_path=source)
    high_water: int | None = None
    replaced = False

    def corrupt(component: str, record: dict[str, object]) -> dict[str, object]:
        nonlocal high_water, replaced
        if component == "simplebroker" and record.get("type") == "header":
            high_water = int(cast(str, record["last_ts"]))
        elif component == "taut-core" and record.get("type") == "membership":
            assert high_water is not None
            record["last_seen_ts"] = str(high_water + 1)
            replaced = True
        return record

    malformed = tmp_path / "future-cursor.taut.jsonl"
    malformed.write_bytes(_rewrite_component_payloads(canonical.read_bytes(), corrupt))
    assert replaced

    with pytest.raises(TautError, match="invalid membership record"):
        TautClient.load(input_path=malformed, db_path=tmp_path / "destination.db")


def test_future_skew_is_apply_time_and_uses_taut_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from simplebroker import DumpClockSkewWarning, format_message_id

    from taut import TautClient, TautError

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    canonical = tmp_path / "canonical.taut.jsonl"
    TautClient.dump(output=canonical, db_path=source)
    future_high_water = format_message_id(time.time_ns() + 10_000_000_000)

    def future_header(component: str, record: dict[str, object]) -> dict[str, object]:
        if component == "simplebroker" and record.get("type") == "header":
            record["last_ts"] = future_high_water
        return record

    future_dump = tmp_path / "future.taut.jsonl"
    future_dump.write_bytes(
        _rewrite_component_payloads(canonical.read_bytes(), future_header)
    )
    monkeypatch.setenv("TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS", "0")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        report = TautClient.load(
            input_path=future_dump,
            db_path=tmp_path / "dry-run.db",
            dry_run=True,
        )
    assert report.dry_run is True
    assert not any(item.category is DumpClockSkewWarning for item in caught)

    destination = tmp_path / "refused.db"
    with (
        pytest.warns(DumpClockSkewWarning),
        pytest.raises(ValueError, match="exceeds configured maximum"),
    ):
        TautClient.load(input_path=future_dump, db_path=destination)
    with pytest.raises(TautError, match="load incomplete; recreate the target"):
        TautClient.init(db_path=destination)

    monkeypatch.setenv("TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS", "20")
    with pytest.warns(DumpClockSkewWarning):
        accepted = TautClient.load(
            input_path=future_dump,
            db_path=tmp_path / "accepted.db",
        )
    assert accepted.applied is True


def test_default_future_skew_boundary_is_300_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from simplebroker import DumpClockSkewWarning, format_message_id

    from taut import TautClient

    monkeypatch.delenv("TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS", raising=False)
    monkeypatch.delenv("BROKER_LOAD_MAX_FUTURE_SKEW_SECONDS", raising=False)
    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    canonical = tmp_path / "canonical.taut.jsonl"
    TautClient.dump(output=canonical, db_path=source)

    def with_skew(seconds: int) -> bytes:
        high_water = format_message_id(time.time_ns() + seconds * 1_000_000_000)

        def change(
            component: str,
            record: dict[str, object],
        ) -> dict[str, object]:
            if component == "simplebroker" and record.get("type") == "header":
                record["last_ts"] = high_water
            return record

        return _rewrite_component_payloads(canonical.read_bytes(), change)

    within = tmp_path / "within-default.taut.jsonl"
    within.write_bytes(with_skew(299))
    with pytest.warns(DumpClockSkewWarning):
        accepted = TautClient.load(
            input_path=within,
            db_path=tmp_path / "accepted.db",
        )
    assert accepted.applied is True

    beyond = tmp_path / "beyond-default.taut.jsonl"
    beyond.write_bytes(with_skew(301))
    with (
        pytest.warns(DumpClockSkewWarning),
        pytest.raises(ValueError, match="maximum of 300 seconds"),
    ):
        TautClient.load(
            input_path=beyond,
            db_path=tmp_path / "refused.db",
        )


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
