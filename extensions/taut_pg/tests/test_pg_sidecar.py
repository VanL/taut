from __future__ import annotations

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psycopg
import pytest
from simplebroker import BrokerSession, Queue, target_for_directory
from simplebroker.ext import IntegrityError, get_backend_plugin
from taut_summon._state import (
    DriverConflictError,
    capture_driver_evidence,
    claim_driver,
    ensure_summon_schema,
    get_session,
    record_session,
)

import taut.state._sql as sql_state
from taut import identity
from taut._config import load_config
from taut._constants import META_QUEUE_NAME
from taut._exceptions import TautError
from taut.client import TautClient
from taut.state import POSTGRES_SQL_DIALECT, SqlSidecarTautState

pytestmark = pytest.mark.pg_only


def test_persistent_client_worker_closes_postgres_session(
    taut_pg_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    peer = TautClient(as_name="peer", persistent=True)
    peer._meta_queue.has_pending()
    peer_session = peer.queue(META_QUEUE_NAME).session
    assert peer_session is not None
    original_close = BrokerSession.close
    close_calls: list[tuple[BrokerSession, int]] = []

    def record_close(session: BrokerSession) -> None:
        close_calls.append((session, threading.get_ident()))
        original_close(session)

    monkeypatch.setattr(BrokerSession, "close", record_close)
    worker_observation: list[tuple[BrokerSession, int]] = []

    def use_and_close_client() -> None:
        worker = TautClient(as_name="worker", persistent=True)
        worker._meta_queue.has_pending()
        worker_session = worker.queue(META_QUEUE_NAME).session
        assert worker_session is not None
        worker_observation.append((worker_session, threading.get_ident()))
        worker.close()

    thread = threading.Thread(target=use_and_close_client)
    thread.start()
    thread.join(timeout=5.0)

    assert not thread.is_alive()
    assert close_calls == worker_observation
    assert close_calls[0][0] is not peer_session
    joined = peer.join("survives")
    assert joined is not None
    assert joined.thread == "survives"
    peer.close()


def test_direct_taut_backend_settings_select_postgres_without_project_file(
    tmp_path: Path,
    pg_dsn: str,
    pg_schema: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TAUT_BACKEND", "postgres")
    monkeypatch.setenv("TAUT_BACKEND_TARGET", pg_dsn)
    monkeypatch.setenv("TAUT_BACKEND_SCHEMA", pg_schema)

    try:
        result = TautClient.init()
        second = TautClient.init()
        client = TautClient(as_name="van")
        try:
            client.join("general")
            assert client.joined_thread_names() == ("general",)
        finally:
            client.close()
        assert result.created is True
        assert second.created is False
        assert result.db.startswith("postgresql://")
        assert not (tmp_path / ".taut.toml").exists()
    finally:
        get_backend_plugin("postgres").cleanup_target(
            pg_dsn,
            backend_options={"schema": pg_schema},
        )


def _assert_advisory_lock_held(
    connection: psycopg.Connection[Any],
    *,
    key: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
            (key,),
        )
        acquired = cursor.fetchone()
    connection.rollback()
    assert acquired == (False,), f"advisory lock {key!r} was not held"


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
    raw_pg_conn: psycopg.Connection[Any],
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
    lock_keys: list[str] = []
    call_count = 0
    count_lock = threading.Lock()
    original_lock = sql_state._acquire_advisory_lock

    def wait_for_release() -> None:
        if not release_first.wait(timeout=10):
            raise RuntimeError("route-lock test coordinator did not release contenders")

    def observe_route_lock(*args: Any, **kwargs: Any) -> None:
        nonlocal call_count
        session = args[0]
        session.run("SET LOCAL lock_timeout = '5s'")
        session.run("SET LOCAL statement_timeout = '10s'")
        with count_lock:
            call_index = call_count
            call_count += 1
            lock_keys.append(str(args[2]))
        if call_index == 0:
            original_lock(*args, **kwargs)
            first_acquired.set()
            wait_for_release()
            return
        second_attempted.set()
        wait_for_release()
        original_lock(*args, **kwargs)

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
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
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
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
            return exc
        return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                futures = [pool.submit(create_member), pool.submit(create_alias)]
                assert first_acquired.wait(timeout=5)
                assert second_attempted.wait(timeout=5)
                assert lock_keys == [
                    "taut:route:contended",
                    "taut:route:contended",
                ]
                _assert_advisory_lock_held(
                    raw_pg_conn,
                    key="taut:route:contended",
                )
            finally:
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
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
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
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
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


def test_postgres_channel_rename_marker_serializes_membership_creation(
    taut_pg_project: Path,
    raw_pg_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(taut_pg_project)
    TautClient.init()
    owner = TautClient(as_name="owner")
    owner.join("general")
    setup_queue = owner.queue(META_QUEUE_NAME)
    setup_state = SqlSidecarTautState(setup_queue, POSTGRES_SQL_DIALECT)
    candidate = setup_state.insert_member(
        member_id=identity.random_member_id(),
        display_name="candidate",
        kind="agent",
        uid=1001,
        host_id="host",
        host_label="host",
        anchor_pid=None,
        anchor_start_time=None,
        fingerprint=None,
        token="rename-membership-race-candidate",
        meta={},
        created_ts=20,
    )
    queues = [owner.queue(META_QUEUE_NAME) for _ in range(2)]
    states = [SqlSidecarTautState(queue, POSTGRES_SQL_DIALECT) for queue in queues]
    rename_holds_lock = threading.Event()
    membership_attempted_lock = threading.Event()
    release_rename = threading.Event()
    original_lock = sql_state._acquire_advisory_lock

    def pause_rename_with_topology_lock(*args: Any, **kwargs: Any) -> None:
        session = args[0]
        key = str(args[2])
        session.run("SET LOCAL lock_timeout = '5s'")
        session.run("SET LOCAL statement_timeout = '10s'")
        if key != "taut:chat-topology":
            original_lock(*args, **kwargs)
            return
        if threading.current_thread().name.startswith("rename-marker"):
            original_lock(*args, **kwargs)
            rename_holds_lock.set()
            assert release_rename.wait(timeout=10)
            return
        membership_attempted_lock.set()
        original_lock(*args, **kwargs)

    monkeypatch.setattr(
        sql_state, "_acquire_advisory_lock", pause_rename_with_topology_lock
    )

    def capture_marker() -> None:
        states[0].start_channel_rename(
            old_name="general",
            new_name="ops",
            expected_affected=[{"old": "general", "new": "ops"}],
            started_ts=30,
        )

    def add_contending_membership() -> None:
        states[1].add_membership(
            thread="general",
            member_id=candidate["member_id"],
            joined_ts=40,
            last_seen_ts=40,
        )

    try:
        with (
            ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="rename-marker",
            ) as rename_pool,
            ThreadPoolExecutor(max_workers=1) as membership_pool,
        ):
            rename_future = rename_pool.submit(capture_marker)
            assert rename_holds_lock.wait(timeout=10)
            membership_future = membership_pool.submit(add_contending_membership)
            assert membership_attempted_lock.wait(timeout=10)
            _assert_advisory_lock_held(raw_pg_conn, key="taut:chat-topology")
            release_rename.set()
            rename_future.result(timeout=20)
            with pytest.raises(TautError, match="incomplete channel rename exists"):
                membership_future.result(timeout=20)

        marker = setup_state.incomplete_channel_renames()
        assert len(marker) == 1
        assert marker[0]["affected"] == [{"old": "general", "new": "ops"}]
        assert (
            setup_state.get_membership(
                thread="general", member_id=candidate["member_id"]
            )
            is None
        )

        setup_state.apply_channel_rename_state(
            old_name="general",
            new_name="ops",
            affected=marker[0]["affected"],
            updated_ts=50,
        )
        assert setup_state.get_thread("general") is None
        assert setup_state.get_thread("ops") is not None
        assert (
            setup_state.get_membership(thread="ops", member_id=candidate["member_id"])
            is None
        )
    finally:
        release_rename.set()
        setup_queue.close()
        for queue in queues:
            queue.close()
        owner.close()


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
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name LIKE 'taut_%%'
                """,
                (pg_schema,),
            )
            required_tables = {
                "taut_channel_renames",
                "taut_identity_claims",
                "taut_member_aliases",
                "taut_members",
                "taut_membership",
                "taut_meta",
                "taut_threads",
            }
            assert required_tables <= {row[0] for row in cursor.fetchall()}
        client = TautClient(as_name="post_init")
        try:
            client.join("general")
            written = client.say("general", "schema is usable after convergence")
            assert client.log("general")[-1] == written
        finally:
            client.close()
    finally:
        for queue in queues:
            queue.close()


def test_postgres_concurrent_taut_client_init_reports_single_creator(
    tmp_path: Path,
    pg_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from conftest import unique_schema

    race_schema = unique_schema("taut_pg_init_race")
    project_dir = tmp_path / "pg-init-race"
    project_dir.mkdir()
    (project_dir / ".taut.toml").write_text(
        "\n".join(
            [
                "version = 1",
                'backend = "postgres"',
                f'target = "{pg_dsn}"',
                "",
                "[backend_options]",
                f'schema = "{race_schema}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(project_dir)
    import taut.state._sql as sql_mod

    workers = 4
    post_preread = threading.Barrier(workers)
    real_check = sql_mod._current_schema_is_installed

    def gated_check(queue: Queue, *, allow_load_guard: bool = False) -> bool:
        installed = real_check(queue, allow_load_guard=allow_load_guard)
        if not installed:
            post_preread.wait(timeout=15)
        return installed

    monkeypatch.setattr(sql_mod, "_current_schema_is_installed", gated_check)

    def run_init(_idx: int) -> Any:
        return TautClient.init(directory=project_dir)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(run_init, range(workers)))
        created_flags = [res.created for res in results]
        assert created_flags.count(True) == 1
        assert created_flags.count(False) == workers - 1
        assert TautClient.init(directory=project_dir).created is False
    finally:
        get_backend_plugin("postgres").cleanup_target(
            pg_dsn,
            backend_options={"schema": race_schema},
        )


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
            except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
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


def test_postgres_ensure_schema_on_current_schema_skips_the_schema_lock(
    taut_pg_project: Path,
    pg_schema: str,
    raw_pg_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Steady-state startup must not queue behind the ``taut:schema`` lock.

    The global advisory lock serializes installation and future migration.
    Once the stored version is current and no load guard exists, a client
    constructed by every CLI command has nothing to install, so it must not
    wait on a concurrent initializer or migrator holding that lock.
    """

    from concurrent.futures import ThreadPoolExecutor, wait

    monkeypatch.chdir(taut_pg_project)
    config = load_config()
    target = target_for_directory(taut_pg_project, config=config)
    setup_queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    SqlSidecarTautState(setup_queue, POSTGRES_SQL_DIALECT).ensure_schema()
    queue = Queue(META_QUEUE_NAME, db_path=target, config=config)
    state = SqlSidecarTautState(queue, POSTGRES_SQL_DIALECT)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="startup-under-lock")
    try:
        with raw_pg_conn.transaction(), raw_pg_conn.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("taut:schema",),
            )
            future = pool.submit(state.ensure_schema)
            done, _pending = wait([future], timeout=5.0)
            blocked = future not in done
        # The lock is released now, so a blocked startup can finish.
        failure = future.exception(timeout=60.0)
        assert not blocked, "ensure_schema waited on the taut:schema advisory lock"
        assert failure is None, f"ensure_schema failed: {failure!r}"
    finally:
        pool.shutdown(wait=True)
        queue.close()
        setup_queue.close()


def test_postgres_install_schema_false_never_creates_migrates_or_falls_back_to_public(
    pg_dsn: str,
    raw_pg_conn: psycopg.Connection[Any],
    tmp_path: Path,
) -> None:
    import uuid

    from taut._exceptions import NotInitializedError

    def make_unique_schema(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def list_schema_tables(schema_name: str) -> set[str]:
        with raw_pg_conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                (schema_name,),
            )
            return {str(row[0]) for row in cur.fetchall()}

    def schema_exists(schema_name: str) -> bool:
        with raw_pg_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                (schema_name,),
            )
            return cur.fetchone() is not None

    def make_project(sub: str, schema_name: str) -> Path:
        root = tmp_path / sub
        root.mkdir(parents=True, exist_ok=True)
        (root / ".taut.toml").write_text(
            "\n".join(
                [
                    "version = 1",
                    'backend = "postgres"',
                    f'target = "{pg_dsn}"',
                    "",
                    "[backend_options]",
                    f'schema = "{schema_name}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return root

    uncreated_schema = make_unique_schema("taut_pg_uncreated")
    older_broker_schema = make_unique_schema("taut_pg_oldbroker")
    public_shadow_empty_schema = make_unique_schema("taut_pg_pubshadow_empty")
    public_shadow_oldbroker_schema = make_unique_schema("taut_pg_pubshadow_old")

    try:
        # 4) Uncreated PostgreSQL schema remains uncreated.
        p_uncreated = make_project("uncreated", uncreated_schema)
        target_uncreated = target_for_directory(p_uncreated, config=load_config())
        with pytest.raises(NotInitializedError):
            TautClient(
                broker_target=target_uncreated,
                broker_config=load_config(),
                install_schema=False,
            )
        assert not schema_exists(uncreated_schema)

        # 5) Older-version broker-only PostgreSQL schema (meta.schema_version = 1) stays 1.
        pg_meta_ddl = (
            "(singleton BOOLEAN PRIMARY KEY DEFAULT TRUE, "
            "magic TEXT NOT NULL, "
            "schema_version INTEGER NOT NULL, "
            "last_ts BIGINT NOT NULL DEFAULT 0, "
            "alias_version BIGINT NOT NULL DEFAULT 0)"
        )
        with raw_pg_conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{older_broker_schema}"')
            cur.execute(f'CREATE TABLE "{older_broker_schema}".meta {pg_meta_ddl}')
            cur.execute(
                f'INSERT INTO "{older_broker_schema}".meta '
                "(singleton, magic, schema_version) VALUES (TRUE, 'simplebroker-v1', 1)"
            )
        p_old = make_project("old_broker", older_broker_schema)
        target_old = target_for_directory(p_old, config=load_config())
        with pytest.raises(NotInitializedError):
            TautClient(
                broker_target=target_old,
                broker_config=load_config(),
                install_schema=False,
            )
        assert list_schema_tables(older_broker_schema) == {"meta"}
        with raw_pg_conn.cursor() as cur:
            cur.execute(
                f'SELECT schema_version FROM "{older_broker_schema}".meta WHERE singleton = TRUE'
            )
            ver = cur.fetchone()
        assert ver == (1,)

        # 6) Create an isolated test-owned PostgreSQL database, populate its public.meta +
        # public.taut_meta, and prove target <schema> never falls back to public via
        # PostgresRunner's search_path ("<schema>, public") and never mutates the shared DB (F3).
        import json

        import psycopg.conninfo
        import simplebroker.db as sb_db

        from taut._exceptions import NotFoundError

        isolated_db = make_unique_schema("taut_pg_pubiso_db")
        isolated_dsn = psycopg.conninfo.make_conninfo(pg_dsn, dbname=isolated_db)
        with raw_pg_conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{isolated_db}"')
        try:
            with psycopg.connect(isolated_dsn, autocommit=True) as iso_conn:

                def make_iso_project(
                    name: str,
                    schema_name: str,
                    *,
                    dsn: str = isolated_dsn,
                ) -> Path:
                    root = tmp_path / name
                    root.mkdir(parents=True, exist_ok=True)
                    (root / ".taut.toml").write_text(
                        "\n".join(
                            [
                                "version = 1",
                                'backend = "postgres"',
                                f"target = {json.dumps(dsn, ensure_ascii=False)}",
                                "",
                                "[backend_options]",
                                f'schema = "{schema_name}"',
                                "",
                            ]
                        ),
                        encoding="utf-8",
                    )
                    return root

                # R3-4 / R4-2: percent-encoded supplementary Unicode in a URI round-trips
                # through make_iso_project's actual .taut.toml writer and tomllib.loads.
                import tomllib

                unicode_dsn = psycopg.conninfo.make_conninfo(
                    "postgresql://u:%F0%9F%94%92@127.0.0.1:5432/shared?dbname=shared",
                    dbname=isolated_db,
                )
                unicode_proj = make_iso_project(
                    "unicode_dsn_roundtrip",
                    "s_unicode",
                    dsn=unicode_dsn,
                )
                parsed_toml = tomllib.loads(
                    (unicode_proj / ".taut.toml").read_text(encoding="utf-8")
                )
                assert parsed_toml["target"] == unicode_dsn
                assert (
                    psycopg.conninfo.conninfo_to_dict(parsed_toml["target"])["dbname"]
                    == isolated_db
                )

                with iso_conn.cursor() as cur:
                    cur.execute("SELECT current_database()")
                    assert cur.fetchone() == (isolated_db,)

                # Initialize one real Taut schema in isolated_db before populating public.meta.
                init_schema = make_unique_schema("taut_pg_f2b_init")
                p_init_owner = make_iso_project("f2b_owner", init_schema)
                TautClient.init(directory=p_init_owner)

                with iso_conn.cursor() as cur:
                    cur.execute(f"CREATE TABLE public.meta {pg_meta_ddl}")
                    cur.execute(
                        "INSERT INTO public.meta (singleton, magic, schema_version) "
                        "VALUES (TRUE, 'simplebroker-v1', 6)"
                    )
                    cur.execute(
                        "CREATE TABLE public.taut_meta "
                        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    cur.execute(
                        "INSERT INTO public.taut_meta (key, value) VALUES (%s, %s)",
                        (sql_state.SCHEMA_VERSION_KEY, str(sql_state.SCHEMA_VERSION)),
                    )
                    cur.execute(f'CREATE SCHEMA "{public_shadow_oldbroker_schema}"')
                    cur.execute(
                        f'CREATE TABLE "{public_shadow_oldbroker_schema}".meta {pg_meta_ddl}'
                    )
                    cur.execute(
                        f'INSERT INTO "{public_shadow_oldbroker_schema}".meta '
                        "(singleton, magic, schema_version) VALUES (TRUE, 'simplebroker-v1', 1)"
                    )

                p_shadow_empty = make_iso_project(
                    "shadow_empty", public_shadow_empty_schema
                )
                target_shadow_empty = target_for_directory(
                    p_shadow_empty, config=load_config()
                )
                with pytest.raises(NotInitializedError):
                    TautClient(
                        broker_target=target_shadow_empty,
                        broker_config=load_config(),
                        install_schema=False,
                    )

                p_shadow_old = make_iso_project(
                    "shadow_old", public_shadow_oldbroker_schema
                )
                target_shadow_old = target_for_directory(
                    p_shadow_old, config=load_config()
                )
                with pytest.raises(NotInitializedError):
                    TautClient(
                        broker_target=target_shadow_old,
                        broker_config=load_config(),
                        install_schema=False,
                    )

                # 7) F2b: fresh .taut.toml pointing at an already-initialized Postgres schema
                # with zero setup markers never invokes SimpleBroker project target admission
                # when install_schema=False probes a missing member (ephemeral or persistent).
                p_fresh_config = make_iso_project("f2b_fresh_reader", init_schema)
                assert list(p_fresh_config.iterdir()) == [p_fresh_config / ".taut.toml"]
                target_fresh = target_for_directory(
                    p_fresh_config, config=load_config()
                )
                with pytest.MonkeyPatch.context() as f2b_patch:
                    f2b_patch.setattr(
                        sb_db,
                        "_initialize_project_backend_target",
                        lambda *_a, **_kw: pytest.fail(
                            "install_schema=False must not run project target admission"
                        ),
                    )
                    for persistent_mode in (False, True):
                        probe_client = TautClient(
                            broker_target=target_fresh,
                            broker_config=load_config(),
                            as_name="missing_member",
                            persistent=persistent_mode,
                            inherit_environment_identity=False,
                            install_schema=False,
                        )
                        try:
                            with pytest.raises(NotFoundError):
                                probe_client.whoami(include_token=True)
                        finally:
                            probe_client.close()
                assert list(p_fresh_config.iterdir()) == [p_fresh_config / ".taut.toml"]

                # 8) R3-2: a PostgreSQL schema with current meta + message indexes + taut_meta
                # but missing its project-local aliases table is rejected by Taut's raw
                # preflight before Queue/BrokerSession open, even if public.aliases exists.
                missing_aliases_schema = make_unique_schema("taut_pg_no_aliases")
                p_no_aliases = make_iso_project(
                    "no_aliases_owner", missing_aliases_schema
                )
                with iso_conn.cursor() as cur:
                    cur.execute("DROP TABLE IF EXISTS public.meta, public.taut_meta")
                TautClient.init(directory=p_no_aliases)
                with iso_conn.cursor() as cur:
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS public.aliases "
                        "(alias TEXT PRIMARY KEY, target TEXT NOT NULL)"
                    )
                    cur.execute(f'DROP TABLE "{missing_aliases_schema}".aliases')
                p_no_aliases_reader = make_iso_project(
                    "no_aliases_reader", missing_aliases_schema
                )
                target_no_aliases = target_for_directory(
                    p_no_aliases_reader, config=load_config()
                )
                from taut._exceptions import TautError

                for persistent_mode in (False, True):
                    with pytest.raises(
                        TautError, match="current schema shape is incomplete"
                    ):
                        TautClient(
                            broker_target=target_no_aliases,
                            broker_config=load_config(),
                            persistent=persistent_mode,
                            install_schema=False,
                        )

                with iso_conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                        (public_shadow_empty_schema,),
                    )
                    assert cur.fetchone() is None
                    cur.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = %s",
                        (public_shadow_oldbroker_schema,),
                    )
                    assert {str(row[0]) for row in cur.fetchall()} == {"meta"}
                    cur.execute(
                        f'SELECT schema_version FROM "{public_shadow_oldbroker_schema}".meta '
                        "WHERE singleton = TRUE"
                    )
                    assert cur.fetchone() == (1,)
        finally:
            with raw_pg_conn.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{isolated_db}" WITH (FORCE)')
    finally:
        with raw_pg_conn.cursor() as cur:
            for s in (
                uncreated_schema,
                older_broker_schema,
            ):
                cur.execute(f'DROP SCHEMA IF EXISTS "{s}" CASCADE')


def test_pg_summon_non_installing_preflight_and_controller_leave_zero_summon_tables(
    taut_pg_project: Path,
    pg_schema: str,
    raw_pg_conn: psycopg.Connection[tuple[object, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    from taut_summon import (
        NothingSummoned,
        ShellSummonInteraction,
        SummonController,
        SummonOperationError,
        SummonRequest,
    )

    from taut import TautClient

    monkeypatch.chdir(taut_pg_project)
    TautClient.init(directory=taut_pg_project)
    c = TautClient(as_name="human")
    try:
        c.join("general")
    finally:
        c.close()

    ctrl = SummonController()
    assert ctrl.list_live() == ()
    with pytest.raises(NothingSummoned):
        ctrl.status("human")
    with pytest.raises(NothingSummoned):
        ctrl.stop("human")

    no_tty = ShellSummonInteraction(
        input_stream=io.StringIO(""),
        output_stream=io.StringIO(),
    )
    for bad_req in (
        SummonRequest(
            name="agent",
            threads=("general",),
            persona=None,
            system_prompt_file=None,
            rate_limit=None,
            attach=False,
            detach=True,
            provider_flag="scripted",
            takeover=False,
            provider_args=("--extra",),
        ),
        SummonRequest(
            name="claude",
            threads=("general",),
            persona=None,
            system_prompt_file=None,
            rate_limit=None,
            attach=False,
            detach=True,
            provider_flag=None,
            takeover=False,
            provider_args=("",),
        ),
        SummonRequest(
            name="claude",
            threads=("general",),
            persona=None,
            system_prompt_file=None,
            rate_limit=None,
            attach=True,
            detach=False,
            provider_flag=None,
            takeover=False,
        ),
    ):
        with pytest.raises(SummonOperationError):
            ctrl.run_foreground(
                bad_req,
                no_tty,
                on_ready=lambda handle: handle.request_stop(),
            )

    with raw_pg_conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (pg_schema,),
        )
        tables = {str(r[0]) for r in cur.fetchall()}
    assert "taut_summon_sessions" not in tables
