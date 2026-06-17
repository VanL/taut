from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
import pytest

from taut import schema
from taut._constants import META_QUEUE_NAME
from taut.client import TautClient

pytestmark = pytest.mark.pg_only


def test_taut_sidecar_schema_initializes_under_postgres(
    taut_pg_project: Path,
    pg_schema: str,
    raw_pg_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_handle="van")
    queue = client.queue(META_QUEUE_NAME)
    try:
        assert schema.get_schema_version(queue) == 1
    finally:
        queue.close()

    with raw_pg_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name IN (
                'taut_meta',
                'taut_members',
                'taut_threads',
                'taut_membership'
              )
            ORDER BY table_name
            """,
            (pg_schema,),
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "taut_members",
            "taut_membership",
            "taut_meta",
            "taut_threads",
        ]


def test_taut_member_uniqueness_uses_postgres_partial_indexes(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_handle="van")
    queue = client.queue(META_QUEUE_NAME)
    try:
        first = schema.insert_member(
            queue,
            handle="van",
            kind="human",
            uid=1000,
            host_id="host",
            host_label="host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token="token-van",
            meta={},
            created_ts=10,
        )
        second = schema.insert_member(
            queue,
            handle="van_copy",
            kind="human",
            uid=1000,
            host_id="host",
            host_label="host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token="token-copy",
            meta={},
            created_ts=20,
        )
    finally:
        queue.close()

    assert first["handle"] == "van"
    assert second["handle"] == "van"
