from __future__ import annotations

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psycopg
import pytest
from simplebroker import Queue, target_for_directory
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
import taut.state._sql as sql_state
from taut._constants import META_QUEUE_NAME, load_config
from taut.client import TautClient
from taut.state import POSTGRES_SQL_DIALECT, SqlSidecarTautState

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
    state = SqlSidecarTautState(queue, POSTGRES_SQL_DIALECT)
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
    state = SqlSidecarTautState(queue, POSTGRES_SQL_DIALECT)
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


def test_postgres_member_create_and_alias_create_share_one_route_namespace(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient()
    setup_queue = client.queue(META_QUEUE_NAME)
    setup_state = SqlSidecarTautState(setup_queue, POSTGRES_SQL_DIALECT)
    alias_owner = setup_state.insert_member(
        member_id=identity.random_member_id(),
        display_name="alias_owner",
        kind="agent",
        uid=1000,
        host_id="host",
        host_label="host",
        anchor_pid=None,
        anchor_start_time=None,
        fingerprint=None,
        token="route-race-alias-owner",
        meta={},
        created_ts=10,
    )
    candidate_id = identity.random_member_id()
    queues = [client.queue(META_QUEUE_NAME) for _ in range(2)]
    states = [SqlSidecarTautState(queue, POSTGRES_SQL_DIALECT) for queue in queues]
    start = threading.Barrier(2)
    first_acquired = threading.Event()
    second_attempted = threading.Event()
    release_first = threading.Event()
    second_acquired = threading.Event()
    call_count = 0
    count_lock = threading.Lock()
    original_lock = sql_state._acquire_advisory_lock

    def observe_route_lock(*args: Any, **kwargs: Any) -> None:
        nonlocal call_count
        with count_lock:
            call_index = call_count
            call_count += 1
        if call_index == 0:
            original_lock(*args, **kwargs)
            first_acquired.set()
            assert release_first.wait(timeout=5)
            return
        second_attempted.set()
        original_lock(*args, **kwargs)
        second_acquired.set()

    monkeypatch.setattr(sql_state, "_acquire_advisory_lock", observe_route_lock)

    def create_member() -> Exception | None:
        start.wait(timeout=5)
        try:
            states[0].insert_member(
                member_id=candidate_id,
                display_name="contended",
                kind="agent",
                uid=1001,
                host_id="host",
                host_label="host",
                anchor_pid=None,
                anchor_start_time=None,
                fingerprint=None,
                token="route-race-member",
                meta={},
                created_ts=20,
            )
        except Exception as exc:
            return exc
        return None

    def create_alias() -> Exception | None:
        start.wait(timeout=5)
        try:
            states[1].add_member_alias(
                member_id=alias_owner["member_id"],
                alias="contended",
                created_ts=20,
            )
        except Exception as exc:
            return exc
        return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create_member), pool.submit(create_alias)]
            assert first_acquired.wait(timeout=5)
            assert second_attempted.wait(timeout=5)
            assert not second_acquired.wait(timeout=0.1)
            release_first.set()
            outcomes = [future.result(timeout=10) for future in futures]
        assert sum(outcome is None for outcome in outcomes) == 1
        assert sum(isinstance(outcome, IntegrityError) for outcome in outcomes) == 1
        owner = setup_state.get_member_by_route_key("contended")
        assert owner is not None
        assert owner["member_id"] in {candidate_id, alias_owner["member_id"]}
    finally:
        setup_queue.close()
        for queue in queues:
            queue.close()


def test_postgres_member_rename_and_alias_create_share_one_route_namespace(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    client = TautClient()
    setup_queue = client.queue(META_QUEUE_NAME)
    setup_state = SqlSidecarTautState(setup_queue, POSTGRES_SQL_DIALECT)
    members = [
        setup_state.insert_member(
            member_id=identity.random_member_id(),
            display_name=name,
            kind="agent",
            uid=1000 + index,
            host_id="host",
            host_label="host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token=f"rename-route-race-{name}",
            meta={},
            created_ts=10 + index,
        )
        for index, name in enumerate(("renamer", "alias_owner"))
    ]
    queues = [client.queue(META_QUEUE_NAME) for _ in range(2)]
    states = [SqlSidecarTautState(queue, POSTGRES_SQL_DIALECT) for queue in queues]
    start = threading.Barrier(2)
    probes = threading.Barrier(2)
    original_probe = sql_state._ensure_route_available

    def synchronize_after_probe(*args: Any, **kwargs: Any) -> None:
        original_probe(*args, **kwargs)
        try:
            probes.wait(timeout=0.25)
        except threading.BrokenBarrierError:
            pass

    monkeypatch.setattr(sql_state, "_ensure_route_available", synchronize_after_probe)

    def rename_member() -> Exception | None:
        start.wait(timeout=5)
        try:
            states[0].update_member_name(members[0]["member_id"], "contended")
        except Exception as exc:
            return exc
        return None

    def create_alias() -> Exception | None:
        start.wait(timeout=5)
        try:
            states[1].add_member_alias(
                member_id=members[1]["member_id"],
                alias="contended",
                created_ts=20,
            )
        except Exception as exc:
            return exc
        return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(rename_member), pool.submit(create_alias)]
            outcomes = [future.result(timeout=10) for future in futures]
        assert sum(outcome is None for outcome in outcomes) == 1
        assert sum(isinstance(outcome, IntegrityError) for outcome in outcomes) == 1
        owner = setup_state.get_member_by_route_key("contended")
        assert owner is not None
        assert owner["member_id"] in {
            members[0]["member_id"],
            members[1]["member_id"],
        }
    finally:
        setup_queue.close()
        for queue in queues:
            queue.close()


def test_postgres_concurrent_empty_schema_initializers_converge(
    taut_pg_project: Path,
    pg_schema: str,
    raw_pg_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    config = load_config()
    target = target_for_directory(taut_pg_project, config=config)
    queues = [Queue(META_QUEUE_NAME, db_path=target, config=config) for _ in range(4)]
    states = [SqlSidecarTautState(queue, POSTGRES_SQL_DIALECT) for queue in queues]
    start = threading.Barrier(len(states))

    def initialize(state: SqlSidecarTautState) -> int | None:
        start.wait(timeout=5)
        state.ensure_schema()
        return state.get_schema_version()

    try:
        with ThreadPoolExecutor(max_workers=len(states)) as pool:
            versions = list(pool.map(initialize, states))
        assert versions == [2] * len(states)
        with raw_pg_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name LIKE 'taut_%%'
                """,
                (pg_schema,),
            )
            assert cursor.fetchone() == (7,)
    finally:
        for queue in queues:
            queue.close()


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
