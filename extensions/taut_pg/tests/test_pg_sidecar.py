from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
import pytest
from simplebroker.ext import IntegrityError

import taut.identity as identity
from taut._constants import META_QUEUE_NAME
from taut.client import TautClient
from taut.state import PORTABLE_SQL_DIALECT, SqlSidecarTautState

pytestmark = pytest.mark.pg_only


def test_taut_sidecar_schema_initializes_under_postgres(
    taut_pg_project: Path,
    pg_schema: str,
    raw_pg_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    state = SqlSidecarTautState(queue, PORTABLE_SQL_DIALECT)
    try:
        assert state.get_schema_version() == 2
    finally:
        queue.close()

    with raw_pg_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name IN (
                'taut_channel_renames',
                'taut_identity_claims',
                'taut_member_aliases',
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
            "taut_channel_renames",
            "taut_identity_claims",
            "taut_member_aliases",
            "taut_members",
            "taut_membership",
            "taut_meta",
            "taut_threads",
        ]


def test_taut_member_route_uniqueness_uses_postgres_constraints(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient(as_name="van")
    queue = client.queue(META_QUEUE_NAME)
    state = SqlSidecarTautState(queue, PORTABLE_SQL_DIALECT)
    try:
        first = state.insert_member(
            member_id=identity.random_member_id(),
            display_name="van",
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
        second = state.insert_member(
            member_id=identity.random_member_id(),
            display_name="van_copy",
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
        with pytest.raises(IntegrityError):
            state.add_member_alias(
                member_id=second["member_id"],
                alias="Van",
                created_ts=30,
            )
    finally:
        queue.close()

    assert first["display_name"] == "van"
    assert second["display_name"] == "van_copy"
