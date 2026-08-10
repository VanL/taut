"""PostgreSQL acceptance tests for portable workspace persistence I/O.

Spec references:
- docs/specs/08-persistence-io.md [PIO-7], [PIO-10], [PIO-11.1]
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from simplebroker import Queue, target_for_directory
from simplebroker.ext import get_backend_plugin

from taut._constants import META_QUEUE_NAME, load_config
from taut._exceptions import TautError
from taut.client import TautClient
from taut.state import SqlSidecarTautState, dialect_for_taut_target

pytestmark = pytest.mark.pg_only


@pytest.fixture
def second_pg_project(tmp_path: Path, pg_dsn: str) -> Iterator[Path]:
    """Return a second fresh PostgreSQL target for cross-schema restore."""

    schema = f"taut_pg_restore_{uuid.uuid4().hex[:12]}"
    project = tmp_path / "restored-pg"
    project.mkdir()
    (project / ".taut.toml").write_text(
        "\n".join(
            [
                "version = 1",
                'backend = "postgres"',
                f"target = {json.dumps(pg_dsn)}",
                "",
                "[backend_options]",
                f'schema = "{schema}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        yield project
    finally:
        get_backend_plugin("postgres").cleanup_target(
            pg_dsn,
            backend_options={"schema": schema},
        )


def _create_message_fixture(
    *,
    db_path: Path | None = None,
) -> tuple[str, str, list[tuple[int, str]]]:
    TautClient.init(db_path=db_path)
    writer = TautClient(db_path=db_path, as_name="van")
    try:
        created_notice = writer.join("before")
        created = writer.last_created_member
        assert created is not None
        assert created.token is not None
        writer._state.add_member_alias(
            member_id=created.member_id,
            alias="operator",
            created_ts=created_notice.ts,
        )
        writer._state.add_identity_claim(
            claim_hash="ic_" + "a" * 52,
            member_id=created.member_id,
            claim_kind="fixture",
            host_id="portable-host",
            host_label="portable host",
            evidence={"source": "persistence-pg-test"},
            seen_ts=created_notice.ts,
        )
        writer.set_channel_topic("before", "portable topic: café")
        writer.say("before", "read boundary")
        peer = TautClient(db_path=db_path, as_name="bob")
        try:
            peer.join("before")
            writer.read("before")
            peer.say("before", "@van portable héllo")
        finally:
            peer.close()
        writer.rename_channel("before", "general")
        [listed] = writer.list_threads()
        assert listed.unread is True
        assert listed.unread_count == 1
        messages = [(message.ts, message.text) for message in writer.log("general")]
        return created.member_id, created.token, messages
    finally:
        writer.close()


def _assert_restored_identity_and_history(
    *,
    member_id: str,
    token: str,
    expected_messages: list[tuple[int, str]],
    db_path: Path | None = None,
) -> None:
    restored = TautClient(db_path=db_path, token=token)
    try:
        assert restored.get_channel("general").topic == "portable topic: café"
        [listed] = restored.list_threads()
        assert listed.unread is True
        assert listed.unread_count == 1
        assert restored.whoami().member_id == member_id
        actual_messages = [
            (message.ts, message.text) for message in restored.log("general")
        ]
        assert actual_messages == expected_messages
        notifications = restored.inbox()
        assert [
            (notice.type, notice.thread, notice.message_ts) for notice in notifications
        ] == [("mention", "before", expected_messages[-1][0])]
        later = restored.say("general", "after restore")
        assert later.ts > max(message_id for message_id, _text in expected_messages)
    finally:
        restored.close()
    alias = TautClient(
        db_path=db_path,
        as_name="operator",
        inherit_environment_identity=False,
    )
    try:
        assert alias.whoami().member_id == member_id
    finally:
        alias.close()


def _component_records(path: Path, name: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    selected = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(raw_line)
        assert isinstance(record, dict)
        if record.get("type") == "component_start":
            selected = record.get("name") == name
        elif record.get("type") == "component_end":
            selected = False
        elif selected:
            records.append(record)
    return records


def _assert_logical_dump_payloads_equal(source: Path, restored: Path) -> None:
    assert _component_records(restored, "taut-core") == _component_records(
        source,
        "taut-core",
    )
    source_messages = [
        record
        for record in _component_records(source, "simplebroker")
        if record.get("type") == "message"
    ]
    restored_messages = [
        record
        for record in _component_records(restored, "simplebroker")
        if record.get("type") == "message"
    ]
    assert restored_messages == source_messages


def test_postgres_round_trip_preserves_exact_ids_and_advances_broker_clock(
    taut_pg_project: Path,
    second_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    member_id, token, messages = _create_message_fixture()
    dump_path = taut_pg_project / "backup.taut.jsonl"
    dumped = TautClient.dump(output=dump_path)

    monkeypatch.chdir(second_pg_project)
    loaded = TautClient.load(input_path=dump_path)
    restored_dump_path = second_pg_project / "restored-backup.taut.jsonl"
    TautClient.dump(output=restored_dump_path)

    assert loaded.applied is True
    assert loaded.components == dumped.components
    assert loaded.queues == dumped.queues
    assert loaded.messages == dumped.messages == len(messages) + 1
    _assert_logical_dump_payloads_equal(dump_path, restored_dump_path)
    _assert_restored_identity_and_history(
        member_id=member_id,
        token=token,
        expected_messages=messages,
    )


def test_sqlite_dump_loads_into_fresh_postgres_and_rejects_second_load(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqlite_source = taut_pg_project / "source.db"
    member_id, token, messages = _create_message_fixture(db_path=sqlite_source)
    dump_path = taut_pg_project / "sqlite-backup.taut.jsonl"
    dumped = TautClient.dump(output=dump_path, db_path=sqlite_source)

    monkeypatch.chdir(taut_pg_project)
    TautClient.init()  # A current initialized but empty schema is load-eligible.
    loaded = TautClient.load(input_path=dump_path)
    restored_dump_path = taut_pg_project / "postgres-redump.taut.jsonl"
    TautClient.dump(output=restored_dump_path)

    assert loaded.applied is True
    assert loaded.components == dumped.components
    assert loaded.messages == len(messages) + 1
    _assert_logical_dump_payloads_equal(dump_path, restored_dump_path)
    _assert_restored_identity_and_history(
        member_id=member_id,
        token=token,
        expected_messages=messages,
    )
    with pytest.raises(TautError, match="destination is not fresh"):
        TautClient.load(input_path=dump_path)


def test_postgres_dump_loads_into_sqlite_with_exact_ids_and_clock(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    member_id, token, messages = _create_message_fixture()
    dump_path = taut_pg_project / "postgres-backup.taut.jsonl"
    dumped = TautClient.dump(output=dump_path)
    sqlite_destination = taut_pg_project / "restored.db"

    loaded = TautClient.load(
        input_path=dump_path,
        db_path=sqlite_destination,
    )
    restored_dump_path = taut_pg_project / "sqlite-redump.taut.jsonl"
    TautClient.dump(output=restored_dump_path, db_path=sqlite_destination)

    assert loaded.applied is True
    assert loaded.components == dumped.components
    assert loaded.queues == dumped.queues
    assert loaded.messages == dumped.messages == len(messages) + 1
    _assert_logical_dump_payloads_equal(dump_path, restored_dump_path)
    _assert_restored_identity_and_history(
        member_id=member_id,
        token=token,
        expected_messages=messages,
        db_path=sqlite_destination,
    )


def test_postgres_load_guard_blocks_init_client_and_dump(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    config = load_config()
    target = target_for_directory(taut_pg_project, config=config)
    queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    try:
        state = SqlSidecarTautState(queue, dialect_for_taut_target(target))
        state.acquire_load_guard()
    finally:
        queue.close()

    diagnostic = "load incomplete; recreate the target"
    with pytest.raises(TautError, match=diagnostic):
        TautClient.init()
    with pytest.raises(TautError, match=diagnostic):
        TautClient(as_name="van")
    with pytest.raises(TautError, match=diagnostic):
        TautClient.dump(output=taut_pg_project / "blocked.dump")


def test_postgres_partial_broker_batch_failure_leaves_target_guarded(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.persistence._format import ParsedDump

    sqlite_source = taut_pg_project / "partial-source.db"
    TautClient.init(db_path=sqlite_source)
    client = TautClient(db_path=sqlite_source, as_name="owner")
    try:
        client.join("general")
    finally:
        client.close()
    source_queue = Queue("general", db_path=str(sqlite_source))
    try:
        # This bounds the probe only. The fault below is triggered by an observed
        # PostgreSQL commit, not by an expected SimpleBroker batch size.
        source_queue.insert_messages(
            (f"bulk-{index}", 3_000_000_000_000_000_000 + index)
            for index in range(10_000)
        )
        source_records = list(source_queue.peek_generator(with_timestamps=True))
    finally:
        source_queue.close()
    dump_path = taut_pg_project / "partial-source.taut.jsonl"
    dumped = TautClient.dump(output=dump_path, db_path=sqlite_source)
    assert dumped.messages == len(source_records)

    original_component_lines = ParsedDump.component_lines
    monkeypatch.chdir(taut_pg_project)
    config = load_config()
    target = target_for_directory(taut_pg_project, config=config)
    observed_prefix: list[tuple[str, int]] = []

    def faulting_component_lines(self: ParsedDump, name: str):  # type: ignore[no-untyped-def]
        lines = original_component_lines(self, name)
        observer: Queue | None = None
        try:
            for line in lines:
                yield line
                if name != "simplebroker":
                    continue
                if observer is None:
                    observer = Queue(
                        "general",
                        db_path=target,
                        persistent=True,
                        config=config,
                    )
                committed = cast(
                    list[tuple[str, int]],
                    list(observer.peek_generator(with_timestamps=True)),
                )
                if committed:
                    observed_prefix.extend(committed)
                    raise RuntimeError("fault after first PostgreSQL broker batch")
        finally:
            lines.close()
            if observer is not None:
                observer.close()

    monkeypatch.setattr(ParsedDump, "component_lines", faulting_component_lines)

    with pytest.raises(
        RuntimeError,
        match="fault after first PostgreSQL broker batch",
    ):
        TautClient.load(input_path=dump_path)

    restored_queue = Queue("general", db_path=target, config=config)
    try:
        restored_records = list(restored_queue.peek_generator(with_timestamps=True))
    finally:
        restored_queue.close()
    assert 0 < len(restored_records) < len(source_records)
    assert observed_prefix == restored_records
    assert restored_records == source_records[: len(restored_records)]

    guard_queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    try:
        with guard_queue.sidecar() as session:
            rows = list(
                session.run(
                    "SELECT value FROM taut_meta WHERE key = ?",
                    ("load_guard",),
                    fetch=True,
                )
            )
    finally:
        guard_queue.close()
    assert rows == [("1",)]
    with pytest.raises(TautError, match="load incomplete; recreate the target"):
        TautClient.init()
