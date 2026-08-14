"""Adversarial SQLite acceptance probes for persistence I/O.

Spec references:
- docs/specs/08-persistence-io.md [PIO-4], [PIO-6.2], [PIO-7], [PIO-9]
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from simplebroker import Queue, open_broker

from taut import TautClient, TautError

pytestmark = pytest.mark.sqlite_only


def _valid_dump(tmp_path: Path) -> tuple[Path, bytes]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="fixture-owner")
    client.join("general")
    client.say("general", "strict UTF-8: héllo")
    client.close()
    output = tmp_path / "valid.taut.jsonl"
    TautClient.dump(output=output, db_path=source)
    return output, output.read_bytes()


def _replace_first_line(
    raw: bytes,
    transform: Callable[[dict[str, object]], object],
) -> bytes:
    lines = raw.splitlines(keepends=True)
    header = json.loads(lines[0])
    assert isinstance(header, dict)
    transformed = transform(header)
    lines[0] = (
        json.dumps(
            transformed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    return b"".join(lines)


def _invalid_utf8(raw: bytes) -> bytes:
    return raw.replace("é".encode(), b"\xff", 1)


def _byte_order_mark(raw: bytes) -> bytes:
    return b"\xef\xbb\xbf" + raw


def _missing_final_lf(raw: bytes) -> bytes:
    return raw[:-1]


def _truncated(raw: bytes) -> bytes:
    return b"".join(raw.splitlines(keepends=True)[:-1])


def _duplicate_json_key(raw: bytes) -> bytes:
    return raw.replace(
        b'"format":"taut-dump"',
        b'"format":"taut-dump","format":"taut-dump"',
        1,
    )


def _wrong_component_hash(raw: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        record = json.loads(line)
        if record.get("type") == "component_end":
            digest = record["sha256"]
            assert isinstance(digest, str)
            record["sha256"] = ("0" if digest[0] != "0" else "1") + digest[1:]
            lines[index] = (
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                + b"\n"
            )
            return b"".join(lines)
    raise AssertionError("valid fixture has no component end")


def _wrong_component_count(raw: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        record = json.loads(line)
        if record.get("type") == "component_end":
            records = record["records"]
            assert isinstance(records, int)
            record["records"] = records + 1
            lines[index] = (
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                + b"\n"
            )
            return b"".join(lines)
    raise AssertionError("valid fixture has no component end")


def _wrong_component_order(raw: bytes) -> bytes:
    def swap(header: dict[str, object]) -> dict[str, object]:
        components = header["components"]
        assert isinstance(components, list)
        header["components"] = list(reversed(components))
        return header

    return _replace_first_line(raw, swap)


def _unknown_outer_version(raw: bytes) -> bytes:
    def change(header: dict[str, object]) -> dict[str, object]:
        header["version"] = 2
        return header

    return _replace_first_line(raw, change)


def _unknown_component(raw: bytes) -> bytes:
    def append(header: dict[str, object]) -> dict[str, object]:
        components = header["components"]
        assert isinstance(components, list)
        components.append({"name": "unknown", "version": 1})
        return header

    return _replace_first_line(raw, append)


def _unknown_header_field(raw: bytes) -> bytes:
    def add(header: dict[str, object]) -> dict[str, object]:
        header["unexpected"] = True
        return header

    return _replace_first_line(raw, add)


def _non_object_header(raw: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    lines[0] = b"[]\n"
    return b"".join(lines)


def _blank_line(raw: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    lines.insert(1, b"\n")
    return b"".join(lines)


def _trailing_record(raw: bytes) -> bytes:
    return raw + b"{}\n"


@pytest.mark.parametrize(
    ("case", "corrupt"),
    [
        ("invalid UTF-8", _invalid_utf8),
        ("byte-order mark", _byte_order_mark),
        ("missing final LF", _missing_final_lf),
        ("truncated", _truncated),
        ("duplicate JSON key", _duplicate_json_key),
        ("wrong component hash", _wrong_component_hash),
        ("wrong component count", _wrong_component_count),
        ("wrong component order", _wrong_component_order),
        ("unknown outer version", _unknown_outer_version),
        ("unknown component", _unknown_component),
        ("unknown header field", _unknown_header_field),
        ("non-object header", _non_object_header),
        ("blank line", _blank_line),
        ("trailing record", _trailing_record),
    ],
)
def test_corrupt_dump_is_rejected_before_destination_creation(
    tmp_path: Path,
    case: str,
    corrupt: Callable[[bytes], bytes],
) -> None:
    _valid_path, valid = _valid_dump(tmp_path)
    input_path = tmp_path / f"corrupt-{case}.taut.jsonl"
    input_path.write_bytes(corrupt(valid))
    destination = tmp_path / "destination.db"

    with pytest.raises(TautError, match="invalid Taut dump"):
        TautClient.load(input_path=input_path, db_path=destination)

    assert not destination.exists()


def test_nonfresh_destination_is_rejected_without_installing_a_guard(
    tmp_path: Path,
) -> None:
    dump_path, _raw = _valid_dump(tmp_path / "source")
    destination = tmp_path / "destination.db"
    TautClient.init(db_path=destination)
    existing = TautClient(db_path=destination, as_name="existing-owner")
    existing.join("existing")
    existing.say("existing", "must survive a rejected load")
    existing.close()

    with pytest.raises(TautError, match="destination is not fresh"):
        TautClient.load(input_path=dump_path, db_path=destination)

    reopened = TautClient(db_path=destination, as_name="existing-owner")
    assert reopened.log("existing")[-1].text == "must survive a rejected load"
    reopened.close()


def test_dry_run_does_not_open_or_mutate_existing_sqlite_destination(
    tmp_path: Path,
) -> None:
    dump_path, _raw = _valid_dump(tmp_path / "source")
    destination = tmp_path / "destination.db"
    TautClient.init(db_path=destination)
    candidates = (destination, Path(f"{destination}-wal"), Path(f"{destination}-shm"))
    before = {path.name: path.read_bytes() for path in candidates if path.exists()}

    report = TautClient.load(
        input_path=dump_path,
        db_path=destination,
        dry_run=True,
    )

    after = {path.name: path.read_bytes() for path in candidates if path.exists()}
    assert after == before
    assert report.destination_checked is False
    assert report.applied is False


def test_remaining_load_guard_blocks_load_and_ordinary_public_operations(
    tmp_path: Path,
) -> None:
    dump_path, _raw = _valid_dump(tmp_path / "source")
    destination = tmp_path / "guarded.db"
    TautClient.init(db_path=destination)
    with (
        Queue("taut_meta", db_path=str(destination)) as queue,
        queue.sidecar(transaction=True) as session,
    ):
        session.run(
            "INSERT INTO taut_meta (key, value) VALUES (?, ?)",
            ("load_guard", "1"),
        )

    blocked = "load incomplete; recreate the target"
    with pytest.raises(TautError, match=blocked):
        TautClient.load(input_path=dump_path, db_path=destination)
    with pytest.raises(TautError, match=blocked):
        TautClient.init(db_path=destination)
    with pytest.raises(TautError, match=blocked):
        TautClient.dump(output=tmp_path / "blocked.jsonl", db_path=destination)
    with pytest.raises(TautError, match=blocked):
        TautClient(db_path=destination, as_name="blocked-owner")


def test_failure_after_real_broker_load_closes_handles_and_leaves_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut.persistence._operations as operations

    dump_path, _raw = _valid_dump(tmp_path / "source")
    destination = tmp_path / "failed.db"
    real_load_lines = operations.load_lines

    def fail_after_load(
        broker: object,
        lines: object,
        **kwargs: object,
    ) -> object:
        real_load_lines(broker, lines, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("fault after real broker load")

    monkeypatch.setattr(operations, "load_lines", fail_after_load)

    with pytest.raises(RuntimeError, match="fault after real broker load"):
        TautClient.load(input_path=dump_path, db_path=destination)

    # A new independent handle can open immediately. The failed loader retained
    # neither its input-file handle nor a Queue/broker connection.
    with (
        Queue("taut_meta", db_path=str(destination)) as queue,
        queue.sidecar() as session,
    ):
        rows = list(
            session.run(
                "SELECT value FROM taut_meta WHERE key = ?",
                ("load_guard",),
                fetch=True,
            )
        )
    assert rows == [("1",)]
    with pytest.raises(TautError, match="load incomplete; recreate the target"):
        TautClient.init(db_path=destination)


def test_failure_after_real_first_broker_batch_leaves_partial_target_guarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.persistence._format import ParsedDump

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="owner")
    client.join("general")
    client.close()
    queue = Queue("general", db_path=str(source))
    try:
        first_timestamp = time.time_ns() - 1_000_000_000
        queue.insert_messages(
            (f"bulk-{index}", first_timestamp + index) for index in range(1001)
        )
    finally:
        queue.close()
    dump_path = tmp_path / "large.taut.jsonl"
    dumped = TautClient.dump(output=dump_path, db_path=source)
    assert dumped.messages > 1000

    original_component_lines = ParsedDump.component_lines

    def faulting_component_lines(self: ParsedDump, name: str):  # type: ignore[no-untyped-def]
        lines = original_component_lines(self, name)
        try:
            for index, line in enumerate(lines):
                if name == "simplebroker" and index == 1001:
                    raise RuntimeError("fault after first broker batch")
                yield line
        finally:
            lines.close()

    monkeypatch.setattr(ParsedDump, "component_lines", faulting_component_lines)
    destination = tmp_path / "partial.db"

    with pytest.raises(RuntimeError, match="fault after first broker batch"):
        TautClient.load(input_path=dump_path, db_path=destination)

    with open_broker(str(destination)) as broker:
        stats = {item.queue: item for item in broker.list_queue_stats()}
    assert stats["general"].pending == 1000
    with pytest.raises(TautError, match="load incomplete; recreate the target"):
        TautClient.init(db_path=destination)


def test_final_guard_clear_failure_leaves_completed_data_unusable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.state import SqlSidecarTautState

    dump_path, _raw = _valid_dump(tmp_path / "source")
    destination = tmp_path / "uncleared.db"

    def fail_clear(_self: SqlSidecarTautState) -> None:
        raise RuntimeError("fault clearing guard")

    monkeypatch.setattr(SqlSidecarTautState, "clear_load_guard", fail_clear)
    with pytest.raises(RuntimeError, match="fault clearing guard"):
        TautClient.load(input_path=dump_path, db_path=destination)

    with pytest.raises(TautError, match="load incomplete; recreate the target"):
        TautClient(db_path=destination, as_name="fixture-owner")


def test_competing_loads_cannot_both_apply_to_one_fresh_target(
    tmp_path: Path,
) -> None:
    dump_path, _raw = _valid_dump(tmp_path / "source")
    destination = tmp_path / "contended.db"
    barrier = Barrier(2)

    def load() -> str:
        barrier.wait()
        try:
            TautClient.load(input_path=dump_path, db_path=destination)
        except TautError:
            return "rejected"
        return "applied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: load(), range(2)))

    assert sorted(results) == ["applied", "rejected"]
    restored = TautClient(db_path=destination, as_name="fixture-owner")
    assert restored.log("general")[-1].text == "strict UTF-8: héllo"
    restored.close()


def test_dump_allows_broker_write_after_snapshot_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut.persistence._operations as operations

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="owner")
    client.join("general")
    client.close()
    output = tmp_path / "backup.taut.jsonl"
    real_payload = operations._broker_payload

    def moving_payload(broker: object, queue_names: tuple[str, ...]):  # type: ignore[no-untyped-def]
        high_water, payload = real_payload(broker, queue_names)

        def move_during_iteration() -> Generator[bytes, None, None]:
            lines = iter(payload)
            try:
                yield next(lines)
                queue = Queue("general", db_path=str(source))
                try:
                    queue.write("concurrent foreign write")
                finally:
                    queue.close()
                yield from lines
            finally:
                close = getattr(lines, "close", None)
                if close is not None:
                    close()

        return high_water, move_during_iteration()

    monkeypatch.setattr(operations, "_broker_payload", moving_payload)

    report = TautClient.dump(output=output, db_path=source)

    assert report.messages >= 0
    restored = tmp_path / "restored.db"
    TautClient.load(input_path=output, db_path=restored)
    restored_client = TautClient(db_path=restored, as_name="owner")
    assert all(
        message.text != "concurrent foreign write"
        for message in restored_client.log("general")
    )
    restored_client.close()
    assert list(tmp_path.glob(".backup.taut.jsonl.*.tmp")) == []


def test_dump_rejects_broker_record_above_sampled_high_water(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut.persistence._operations as operations

    def invalid_dump_lines(
        *args: object, **kwargs: object
    ) -> Generator[str, None, None]:
        del args, kwargs
        yield json.dumps(
            {
                "backend": "sqlite",
                "format": "simplebroker-dump",
                "last_ts": "0000000000000000100",
                "type": "header",
                "version": 1,
            }
        )
        yield json.dumps(
            {
                "body": "future",
                "id": "0000000000000000101",
                "queue": "general",
                "type": "message",
            }
        )

    monkeypatch.setattr(operations, "dump_lines", invalid_dump_lines)

    _high_water, payload = operations._broker_payload(object(), ("general",))
    with pytest.raises(TautError, match="message above its snapshot boundary"):
        list(payload)


def test_dump_retains_exact_boundary_once_across_racing_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from simplebroker.db import BrokerDB

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="owner")
    client.join("alpha")
    client.join("beta")
    moved = client.say("alpha", "move during dump")
    client.close()
    original = BrokerDB.peek_generator
    move_count = 0

    def move_after_alpha(self: BrokerDB, queue_name: str, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal move_count
        yield from original(self, queue_name, **kwargs)  # type: ignore[arg-type]
        if queue_name == "alpha":
            queue = Queue("alpha", db_path=str(source))
            try:
                result = queue.move("beta", message_id=moved.ts)
            finally:
                queue.close()
            assert result is not None
            move_count += 1

    monkeypatch.setattr(BrokerDB, "peek_generator", move_after_alpha)
    output = tmp_path / "backup.taut.jsonl"

    TautClient.dump(output=output, db_path=source)

    retained = [
        record
        for record in map(json.loads, output.read_text().splitlines())
        if record.get("type") == "message" and int(record["id"]) == moved.ts
    ]
    assert move_count == 1
    assert len(retained) == 1


def test_dump_allows_sidecar_movement_after_its_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taut.state import SqlSidecarTautState

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    original = SqlSidecarTautState.persistence_records

    def moving_records(state: SqlSidecarTautState) -> list[dict[str, Any]]:
        records = original(state)
        client = TautClient(db_path=source, as_name="late-writer")
        client.join("late")
        client.close()
        return records

    monkeypatch.setattr(SqlSidecarTautState, "persistence_records", moving_records)

    output = tmp_path / "backup.taut.jsonl"
    TautClient.dump(output=output, db_path=source)
    restored = tmp_path / "restored.db"
    TautClient.load(input_path=output, db_path=restored)


def test_dump_clamps_copied_membership_cursor_to_broker_high_water(
    tmp_path: Path,
) -> None:
    from taut.state import SqlSidecarTautState, dialect_for_taut_target

    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    client = TautClient(db_path=source, as_name="owner")
    client.join("general")
    member = client.last_created_member
    assert member is not None
    client.close()
    future_cursor = 9_223_372_036_854_775_807
    queue = Queue("taut_meta", db_path=str(source))
    try:
        state = SqlSidecarTautState(queue, dialect_for_taut_target(str(source)))
        state.advance_cursor(
            thread="general",
            member_id=member.member_id,
            seen_ts=future_cursor,
        )
    finally:
        queue.close()
    output = tmp_path / "backup.taut.jsonl"
    TautClient.dump(output=output, db_path=source)

    component: str | None = None
    high_water: int | None = None
    membership_cursors: list[int] = []
    for raw in output.read_text().splitlines():
        record = json.loads(raw)
        if record.get("type") == "component_start":
            component = record["name"]
        elif record.get("type") == "component_end":
            component = None
        elif component == "simplebroker" and record.get("type") == "header":
            high_water = int(record["last_ts"])
        elif component == "taut-core" and record.get("type") == "membership":
            membership_cursors.append(int(record["last_seen_ts"]))

    assert high_water is not None
    assert membership_cursors
    assert all(cursor <= high_water for cursor in membership_cursors)
    queue = Queue("taut_meta", db_path=str(source))
    try:
        live = SqlSidecarTautState(
            queue, dialect_for_taut_target(str(source))
        ).get_membership(
            thread="general",
            member_id=member.member_id,
        )
    finally:
        queue.close()
    assert live is not None
    assert live["last_seen_ts"] == future_cursor


@pytest.mark.parametrize(
    "alias_kind",
    ["database", "wal", "shm", "symlink", "hardlink"],
)
def test_dump_rejects_sqlite_storage_aliases_before_touching_source(
    tmp_path: Path,
    alias_kind: str,
) -> None:
    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    if alias_kind == "database":
        output = source
    elif alias_kind in {"wal", "shm"}:
        output = Path(f"{source}-{alias_kind}")
    else:
        output = tmp_path / f"source-{alias_kind}.db"
        if alias_kind == "symlink":
            output.symlink_to(source)
        else:
            os.link(source, output)

    with pytest.raises(TautError, match="SQLite database, WAL, or SHM"):
        TautClient.dump(output=output, db_path=source)

    safe_dump = tmp_path / f"safe-after-{alias_kind}.jsonl"
    assert TautClient.dump(output=safe_dump, db_path=source).path == str(safe_dump)


@pytest.mark.parametrize(
    "alias_kind",
    ["database", "wal", "shm", "symlink", "hardlink"],
)
def test_load_dry_run_rejects_sqlite_storage_aliases_without_mutation(
    tmp_path: Path,
    alias_kind: str,
) -> None:
    _dump_path, valid = _valid_dump(tmp_path / "source")
    destination = tmp_path / "selected.db"
    if alias_kind == "database":
        input_path = destination
        input_path.write_bytes(valid)
    elif alias_kind in {"wal", "shm"}:
        input_path = Path(f"{destination}-{alias_kind}")
        input_path.write_bytes(valid)
    else:
        destination.write_bytes(valid)
        input_path = tmp_path / f"input-{alias_kind}.jsonl"
        if alias_kind == "symlink":
            input_path.symlink_to(destination)
        else:
            os.link(destination, input_path)
    before = input_path.read_bytes()

    with pytest.raises(TautError, match="SQLite database, WAL, or SHM"):
        TautClient.load(
            input_path=input_path,
            db_path=destination,
            dry_run=True,
        )

    assert input_path.read_bytes() == before
    if alias_kind in {"wal", "shm"}:
        assert not destination.exists()


def test_failed_dump_keeps_prior_output_and_removes_staging_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    TautClient.init(db_path=source)
    output_dir = tmp_path / "locked"
    output_dir.mkdir()
    output = output_dir / "backup.jsonl"
    previous = b"previous complete backup\n"
    output.write_bytes(previous)
    output_dir.chmod(0o500)
    try:
        if os.access(output_dir, os.W_OK):
            pytest.skip("mode bits do not make this directory unwritable")
        with pytest.raises(TautError, match="cannot create dump staging file"):
            TautClient.dump(output=output, db_path=source)
    finally:
        output_dir.chmod(0o700)

    assert output.read_bytes() == previous
    assert list(output_dir.glob(".backup.jsonl.*.tmp")) == []
