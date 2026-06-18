from __future__ import annotations

from pathlib import Path

import pytest
from simplebroker import Queue

from taut import schema
from taut._constants import META_QUEUE_NAME
from taut._exceptions import SchemaVersionError

pytestmark = pytest.mark.sqlite_only


def meta_queue(tmp_path: Path) -> Queue:
    return Queue(META_QUEUE_NAME, db_path=str(tmp_path / ".taut.db"))


def test_schema_initializes_idempotently(tmp_path: Path) -> None:
    queue = meta_queue(tmp_path)

    schema.ensure_schema(queue)
    schema.ensure_schema(queue)

    assert schema.get_schema_version(queue) == 1


def test_schema_refuses_newer_version(tmp_path: Path) -> None:
    queue = meta_queue(tmp_path)
    schema.ensure_schema(queue)
    with queue.sidecar(transaction=True) as session:
        session.run(
            "UPDATE taut_meta SET value = ? WHERE key = ?",
            ("99", schema.SCHEMA_VERSION_KEY),
        )

    with pytest.raises(SchemaVersionError):
        schema.ensure_schema(queue)


def test_cursor_advance_is_monotonic(tmp_path: Path) -> None:
    queue = meta_queue(tmp_path)
    schema.ensure_schema(queue)
    schema.upsert_thread(
        queue,
        name="general",
        parent=None,
        origin_ts=None,
        created_by="van",
        created_ts=10,
    )
    schema.insert_member(
        queue,
        handle="van",
        kind="human",
        uid=1,
        host_id="host",
        host_label="host",
        anchor_pid=None,
        anchor_start_time=None,
        fingerprint=None,
        token="taut-token",
        meta={},
        created_ts=10,
    )
    schema.add_membership(
        queue,
        thread="general",
        member="van",
        joined_ts=10,
        last_seen_ts=100,
    )

    schema.advance_cursor(queue, thread="general", member="van", seen_ts=90)
    schema.advance_cursor(queue, thread="general", member="van", seen_ts=110)

    membership = schema.get_membership(queue, thread="general", member="van")
    assert membership is not None
    assert membership["last_seen_ts"] == 110
