from __future__ import annotations

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psycopg
import pytest
from simplebroker.ext import IntegrityError
from taut_summon._state import (
    DriverConflictError,
    capture_driver_evidence,
    claim_driver,
    ensure_summon_schema,
    get_session,
    record_session,
)

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


def test_summon_driver_claim_race_has_one_exact_postgres_owner(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient()
    setup_queue = client.queue("taut.summon_state")
    claimant_queues = [client.queue("taut.summon_state") for _ in range(2)]
    children = [
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        for _ in range(2)
    ]
    try:
        ensure_summon_schema(setup_queue)
        record_session(
            setup_queue,
            member_id="m_pg_race",
            token="taut-tok-pg-race",
            provider="claude",
            updated_ts=setup_queue.generate_timestamp(),
        )
        evidence = [capture_driver_evidence(child.pid) for child in children]
        barrier = threading.Barrier(2)

        def race_claim(index: int) -> tuple[int, str] | Exception:
            queue = claimant_queues[index]
            candidate = evidence[index]
            try:
                barrier.wait(timeout=5)
                claimed = claim_driver(
                    queue,
                    member_id="m_pg_race",
                    driver_pid=candidate[0],
                    driver_start_time=candidate[1],
                    updated_ts=queue.generate_timestamp(),
                )
                assert (
                    claimed["driver_pid"],
                    claimed["driver_start_time"],
                ) == candidate
                return candidate
            except Exception as exc:  # returned for symmetric race assertions
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(race_claim, range(2)))

        winners = [outcome for outcome in outcomes if isinstance(outcome, tuple)]
        conflicts = [
            outcome for outcome in outcomes if isinstance(outcome, DriverConflictError)
        ]
        assert len(winners) == 1
        assert len(conflicts) == 1
        assert winners[0] in evidence
        stored = get_session(setup_queue, "m_pg_race")
        assert stored is not None
        assert (stored["driver_pid"], stored["driver_start_time"]) == winners[0]
    finally:
        setup_queue.close()
        for queue in claimant_queues:
            queue.close()
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
