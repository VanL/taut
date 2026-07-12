"""Session-ledger and single-driver-guard tests for the summon extension.

Contract under test: docs/specs/04-summon.md [SUM-8] — the two-table
ledger split (transient ``taut_summon_claims``, durable member_id-keyed
``taut_summon_sessions``), the extension-owned ``summon_schema_version``
meta key with a fail-closed gate, and the evidence-based single-driver
guard (pid + start-time liveness, ``--takeover`` semantics).

Anti-mocking posture ([SUM-12]): every test runs against a real SQLite
taut database created by ``TautClient.init``; driver liveness evidence is
a real child process, never a faked pid table.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import taut_summon._state as state_module
from simplebroker import Queue
from simplebroker.ext import DatabaseError, IntegrityError
from taut_summon._state import (
    SUMMON_SCHEMA_VERSION,
    SUMMON_SCHEMA_VERSION_KEY,
    ClaimConflictError,
    DriverConflictError,
    SummonSchemaVersionError,
    SummonStateError,
    capture_driver_evidence,
    claim_driver,
    claim_name,
    driver_liveness,
    ensure_summon_schema,
    get_claim,
    get_session,
    get_summon_schema_version,
    get_wired,
    list_sessions,
    record_session,
    release_claim,
    release_driver,
    set_wired,
    update_session,
)

from taut.client import TautClient

pytestmark = pytest.mark.sqlite_only


@pytest.fixture
def summon_db(tmp_path: Path) -> Path:
    """Create a real taut database and return its path."""

    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    return db


@pytest.fixture
def state_queue(summon_db: Path) -> Iterator[Queue]:
    """Return a broker queue handle bound to the test database."""

    queue = Queue("taut.summon_state", db_path=str(summon_db))
    try:
        yield queue
    finally:
        queue.close()


@pytest.fixture
def live_child() -> Iterator[subprocess.Popen[bytes]]:
    """Spawn a real child process to serve as a live fake driver."""

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def _meta_value(queue: Queue, key: str) -> str | None:
    with queue.sidecar() as session:
        rows = list(
            session.run("SELECT value FROM taut_meta WHERE key = ?", (key,), fetch=True)
        )
    return None if not rows else str(rows[0][0])


def _set_meta_value(queue: Queue, key: str, value: str) -> None:
    with queue.sidecar(transaction=True) as session:
        session.run("UPDATE taut_meta SET value = ? WHERE key = ?", (value, key))


def _dead_evidence() -> tuple[int, str]:
    """Return pid + start-time evidence for a real, already-exited child."""

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        evidence = capture_driver_evidence(proc.pid)
    finally:
        proc.kill()
        proc.wait()
    return evidence


# --- schema install and version gate ---------------------------------------


def test_ensure_summon_schema_is_idempotent(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    ensure_summon_schema(state_queue)

    assert get_summon_schema_version(state_queue) == SUMMON_SCHEMA_VERSION

    # Both tables exist and are usable after the double install.
    ts = state_queue.generate_timestamp()
    pid, start = capture_driver_evidence()
    claim_name(
        state_queue,
        name="claude",
        provider="claude",
        driver_pid=pid,
        driver_start_time=start,
        claimed_ts=ts,
    )
    assert get_claim(state_queue, name="claude", provider="claude") is not None
    record_session(
        state_queue,
        member_id="m_test",
        token="taut-test-token",
        provider="claude",
        updated_ts=ts,
    )
    assert get_session(state_queue, "m_test") is not None


def test_version_gate_refuses_newer_schema(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    _set_meta_value(
        state_queue, SUMMON_SCHEMA_VERSION_KEY, str(SUMMON_SCHEMA_VERSION + 1)
    )

    with pytest.raises(SummonSchemaVersionError, match="newer"):
        ensure_summon_schema(state_queue)

    # Fail-closed: the stored version is untouched by the refused install.
    assert get_summon_schema_version(state_queue) == SUMMON_SCHEMA_VERSION + 1


def test_version_gate_refuses_older_schema(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    _set_meta_value(state_queue, SUMMON_SCHEMA_VERSION_KEY, "1")

    with pytest.raises(SummonSchemaVersionError):
        ensure_summon_schema(state_queue)


def test_version_two_migrates_claim_names_to_lowercase_route_keys(
    state_queue: Queue,
) -> None:
    ensure_summon_schema(state_queue)
    with state_queue.sidecar(transaction=True) as session:
        session.run("DROP INDEX IF EXISTS taut_summon_claim_route_key_uq")
    _set_meta_value(state_queue, SUMMON_SCHEMA_VERSION_KEY, "2")
    with state_queue.sidecar(transaction=True) as session:
        session.run(
            """
            INSERT INTO taut_summon_claims (
                name, provider, driver_pid, driver_start_time, claimed_ts
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("Reviewer", "scripted", 123, "legacy-start", 1),
        )

    ensure_summon_schema(state_queue)

    assert get_summon_schema_version(state_queue) == 3
    migrated = get_claim(state_queue, name="REVIEWER", provider="scripted")
    assert migrated is not None
    assert migrated["name"] == "reviewer"


def test_version_two_case_variant_claims_fail_before_migration(
    state_queue: Queue,
) -> None:
    ensure_summon_schema(state_queue)
    with state_queue.sidecar(transaction=True) as session:
        session.run("DROP INDEX IF EXISTS taut_summon_claim_route_key_uq")
    _set_meta_value(state_queue, SUMMON_SCHEMA_VERSION_KEY, "2")
    with state_queue.sidecar(transaction=True) as session:
        for name, pid in (("Reviewer", 123), ("reviewer", 456)):
            session.run(
                """
                INSERT INTO taut_summon_claims (
                    name, provider, driver_pid, driver_start_time, claimed_ts
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (name, "scripted", pid, f"legacy-{pid}", pid),
            )

    with pytest.raises(SummonSchemaVersionError, match="case-variant claims"):
        ensure_summon_schema(state_queue)

    assert get_summon_schema_version(state_queue) == 2
    with state_queue.sidecar() as session:
        rows = list(
            session.run(
                """
                SELECT name FROM taut_summon_claims
                WHERE provider = ? ORDER BY name
                """,
                ("scripted",),
                fetch=True,
            )
        )
    assert {str(row[0]) for row in rows} == {"Reviewer", "reviewer"}


def test_version_three_index_and_lookup_cover_a_late_version_two_writer(
    state_queue: Queue,
) -> None:
    ensure_summon_schema(state_queue)
    with state_queue.sidecar(transaction=True) as session:
        session.run(
            """
            INSERT INTO taut_summon_claims (
                name, provider, driver_pid, driver_start_time, claimed_ts
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("Legacy", "scripted", 123, "legacy-start", 1),
        )

    visible = get_claim(state_queue, name="legacy", provider="scripted")
    assert visible is not None
    assert visible["name"] == "Legacy"

    with pytest.raises(IntegrityError):
        with state_queue.sidecar(transaction=True) as session:
            session.run(
                """
                INSERT INTO taut_summon_claims (
                    name, provider, driver_pid, driver_start_time, claimed_ts
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("legacy", "scripted", 456, "new-start", 2),
            )

    assert release_claim(
        state_queue,
        name="LEGACY",
        provider="scripted",
        driver_pid=123,
        driver_start_time="legacy-start",
    )


def test_summon_schema_leaves_core_version_key_alone(state_queue: Queue) -> None:
    core_before = _meta_value(state_queue, "schema_version")
    assert core_before is not None

    ensure_summon_schema(state_queue)

    assert _meta_value(state_queue, "schema_version") == core_before
    assert _meta_value(state_queue, SUMMON_SCHEMA_VERSION_KEY) == str(
        SUMMON_SCHEMA_VERSION
    )


# --- sessions CRUD ----------------------------------------------------------


def test_record_session_get_round_trip(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    ts = state_queue.generate_timestamp()
    pid, start = capture_driver_evidence()

    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        provider_session_id="sess-1",
        driver_pid=pid,
        driver_start_time=start,
        updated_ts=ts,
    )
    row = get_session(state_queue, "m_abc")

    assert row is not None
    assert row["member_id"] == "m_abc"
    assert row["token"] == "taut-tok-1"
    assert row["provider"] == "claude"
    assert row["provider_session_id"] == "sess-1"
    assert row["driver_pid"] == pid
    assert row["driver_start_time"] == start
    assert row["wired"] is False
    assert row["updated_ts"] == ts


def test_record_session_upsert_is_idempotent(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    ts1 = state_queue.generate_timestamp()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        provider_session_id="sess-1",
        updated_ts=ts1,
    )

    ts2 = state_queue.generate_timestamp()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        provider_session_id="sess-2",
        updated_ts=ts2,
    )

    row = get_session(state_queue, "m_abc")
    assert row is not None
    assert row["provider_session_id"] == "sess-2"
    assert row["updated_ts"] == ts2


def test_update_session_changes_provider_session_id(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        updated_ts=state_queue.generate_timestamp(),
    )

    ts = state_queue.generate_timestamp()
    update_session(
        state_queue,
        member_id="m_abc",
        provider_session_id="sess-9",
        updated_ts=ts,
    )

    row = get_session(state_queue, "m_abc")
    assert row is not None
    assert row["provider_session_id"] == "sess-9"
    assert row["updated_ts"] == ts
    # Untouched columns survive the partial update.
    assert row["token"] == "taut-tok-1"


def test_session_round_trip_uses_canonical_projection(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    pid, start = capture_driver_evidence()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="scripted",
        provider_session_id="sess-1",
        updated_ts=state_queue.generate_timestamp(),
    )
    set_wired(
        state_queue,
        member_id="m_abc",
        value=True,
        updated_ts=state_queue.generate_timestamp(),
    )
    claimed = claim_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=pid,
        driver_start_time=start,
        updated_ts=state_queue.generate_timestamp(),
    )
    assert claimed["wired"] is True

    row = update_session(
        state_queue,
        member_id="m_abc",
        provider_session_id="sess-2",
        updated_ts=state_queue.generate_timestamp(),
    )
    assert row["provider_session_id"] == "sess-2"
    assert row["driver_pid"] == pid
    assert row["driver_start_time"] == start
    assert row["wired"] is True

    assert release_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=pid,
        driver_start_time=start,
        updated_ts=state_queue.generate_timestamp(),
    )
    rows = list_sessions(state_queue)
    assert len(rows) == 1
    assert rows[0]["member_id"] == "m_abc"
    assert rows[0]["provider_session_id"] == "sess-2"
    assert rows[0]["driver_pid"] is None


def test_get_session_shifted_row_shape_fails_without_retry(
    state_queue: Queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_summon_schema(state_queue)
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="scripted",
        provider_session_id="sess-1",
        updated_ts=state_queue.generate_timestamp(),
    )

    real_one = state_module._one
    malformed_reads = 0

    def flaky_one(session: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
        nonlocal malformed_reads
        if "FROM taut_summon_sessions" in sql:
            malformed_reads += 1
            return (
                "m_abc",
                "taut-tok-1",
                "scripted",
                "sess-1",
                None,
                None,
                "runnervmkkn4f",
                1,
            )
        return real_one(session, sql, params)

    monkeypatch.setattr(state_module, "_one", flaky_one)

    with pytest.raises(DatabaseError, match="malformed summon session row"):
        get_session(state_queue, "m_abc")

    assert malformed_reads == 1


def test_wired_round_trips_and_survives_driver_claim(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="pty",
        updated_ts=state_queue.generate_timestamp(),
    )
    assert get_wired(state_queue, "m_abc") is False

    set_wired(
        state_queue,
        member_id="m_abc",
        value=True,
        updated_ts=state_queue.generate_timestamp(),
    )
    assert get_wired(state_queue, "m_abc") is True

    my_pid, my_start = capture_driver_evidence()
    claimed = claim_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
    )

    assert claimed["wired"] is True
    assert get_wired(state_queue, "m_abc") is True


def test_record_session_update_preserves_wired(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="pty",
        updated_ts=state_queue.generate_timestamp(),
    )
    set_wired(
        state_queue,
        member_id="m_abc",
        value=True,
        updated_ts=state_queue.generate_timestamp(),
    )

    updated = record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-2",
        provider="pty",
        provider_session_id=None,
        updated_ts=state_queue.generate_timestamp(),
    )

    assert updated["token"] == "taut-tok-2"
    assert updated["wired"] is True


def test_get_session_missing_returns_none(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)

    assert get_session(state_queue, "m_missing") is None


@pytest.mark.parametrize(
    ("driver_pid", "driver_start_time"),
    ((123, None), (None, "start-token")),
)
def test_record_session_rejects_partial_driver_evidence(
    state_queue: Queue,
    driver_pid: int | None,
    driver_start_time: str | None,
) -> None:
    ensure_summon_schema(state_queue)

    with pytest.raises(SummonStateError, match="both set or both null"):
        record_session(
            state_queue,
            member_id="m_abc",
            token="taut-tok-1",
            provider="claude",
            driver_pid=driver_pid,
            driver_start_time=driver_start_time,
            updated_ts=state_queue.generate_timestamp(),
        )

    assert get_session(state_queue, "m_abc") is None


def test_record_session_readback_failure_rolls_back_write(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    with state_queue.sidecar(transaction=True) as session:
        session.run(
            """
            CREATE TRIGGER corrupt_summon_session_after_insert
            AFTER INSERT ON taut_summon_sessions
            BEGIN
                UPDATE taut_summon_sessions
                SET wired = 2
                WHERE member_id = NEW.member_id;
            END
            """
        )

    with pytest.raises(DatabaseError, match="malformed summon session row"):
        record_session(
            state_queue,
            member_id="m_abc",
            token="taut-tok-1",
            provider="claude",
            driver_pid=None,
            driver_start_time=None,
            updated_ts=state_queue.generate_timestamp(),
        )

    with state_queue.sidecar() as session:
        rows = list(
            session.run(
                "SELECT member_id FROM taut_summon_sessions WHERE member_id = ?",
                ("m_abc",),
                fetch=True,
            )
        )
    assert rows == []


@pytest.mark.parametrize(
    ("driver_pid", "driver_start_time"),
    ((123, None), (None, "start-token")),
)
def test_driver_liveness_classifies_partial_evidence_as_indeterminate(
    state_queue: Queue,
    driver_pid: int | None,
    driver_start_time: str | None,
) -> None:
    ensure_summon_schema(state_queue)
    record_session(
        state_queue,
        member_id="m_legacy",
        token="taut-tok-legacy",
        provider="claude",
        updated_ts=state_queue.generate_timestamp(),
    )
    with state_queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_summon_sessions
            SET driver_pid = ?, driver_start_time = ?
            WHERE member_id = ?
            """,
            (driver_pid, driver_start_time, "m_legacy"),
        )
    row = get_session(state_queue, "m_legacy")
    assert row is not None

    assert driver_liveness(row) == "indeterminate"


def test_session_sql_templates_are_static_and_canonical() -> None:
    select_one = state_module._SESSION_SELECT_BY_MEMBER
    select_all = state_module._SESSION_SELECT_ALL
    expected_columns = " ".join(
        (
            "member_id, token, provider, provider_session_id,",
            "driver_pid, driver_start_time, wired, updated_ts",
        )
    )
    normalized_one = " ".join(select_one.split())
    normalized_all = " ".join(select_all.split())

    assert expected_columns in normalized_one
    assert expected_columns in normalized_all
    assert "SELECT *" not in select_one.upper()
    assert "SELECT *" not in select_all.upper()
    assert "WHERE member_id = ?" in select_one
    assert "ORDER BY updated_ts DESC" in select_all


# --- single-driver guard ([SUM-8]) ------------------------------------------


def test_claim_driver_refuses_live_driver(
    state_queue: Queue, live_child: subprocess.Popen[bytes]
) -> None:
    ensure_summon_schema(state_queue)
    child_pid, child_start = capture_driver_evidence(live_child.pid)
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        driver_pid=child_pid,
        driver_start_time=child_start,
        updated_ts=state_queue.generate_timestamp(),
    )
    my_pid, my_start = capture_driver_evidence()

    with pytest.raises(DriverConflictError, match="live"):
        claim_driver(
            state_queue,
            member_id="m_abc",
            driver_pid=my_pid,
            driver_start_time=my_start,
            updated_ts=state_queue.generate_timestamp(),
        )

    # --takeover replaces dead or abandoned claims, never a live driver.
    with pytest.raises(DriverConflictError, match="live"):
        claim_driver(
            state_queue,
            member_id="m_abc",
            driver_pid=my_pid,
            driver_start_time=my_start,
            updated_ts=state_queue.generate_timestamp(),
            takeover=True,
        )

    row = get_session(state_queue, "m_abc")
    assert row is not None
    assert row["driver_pid"] == child_pid


def test_claim_driver_allows_takeover_of_dead_claim(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    dead_pid, dead_start = _dead_evidence()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        driver_pid=dead_pid,
        driver_start_time=dead_start,
        updated_ts=state_queue.generate_timestamp(),
    )
    my_pid, my_start = capture_driver_evidence()

    row = claim_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
        takeover=True,
    )

    assert row["driver_pid"] == my_pid
    assert row["driver_start_time"] == my_start


@pytest.mark.parametrize(
    ("held_pid", "held_start"),
    ((123, None), (None, "legacy-start")),
)
def test_claim_driver_refuses_indeterminate_partial_evidence_without_takeover(
    state_queue: Queue,
    held_pid: int | None,
    held_start: str | None,
) -> None:
    ensure_summon_schema(state_queue)
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        updated_ts=state_queue.generate_timestamp(),
    )
    with state_queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_summon_sessions
            SET driver_pid = ?, driver_start_time = ?
            WHERE member_id = ?
            """,
            (held_pid, held_start, "m_abc"),
        )
    my_pid, my_start = capture_driver_evidence()

    with pytest.raises(DriverConflictError, match="cannot verify"):
        claim_driver(
            state_queue,
            member_id="m_abc",
            driver_pid=my_pid,
            driver_start_time=my_start,
            updated_ts=state_queue.generate_timestamp(),
        )


@pytest.mark.parametrize(
    ("held_pid", "held_start"),
    ((123, None), (None, "legacy-start")),
)
def test_claim_driver_takeover_replaces_partial_driver_evidence(
    state_queue: Queue,
    held_pid: int | None,
    held_start: str | None,
) -> None:
    ensure_summon_schema(state_queue)
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        updated_ts=state_queue.generate_timestamp(),
    )
    with state_queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_summon_sessions
            SET driver_pid = ?, driver_start_time = ?
            WHERE member_id = ?
            """,
            (held_pid, held_start, "m_abc"),
        )
    my_pid, my_start = capture_driver_evidence()

    claimed = claim_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
        takeover=True,
    )

    assert claimed["driver_pid"] == my_pid
    assert claimed["driver_start_time"] == my_start


def test_claim_driver_rejects_zero_row_write_postcondition(
    state_queue: Queue,
) -> None:
    ensure_summon_schema(state_queue)
    dead_pid, dead_start = _dead_evidence()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        driver_pid=dead_pid,
        driver_start_time=dead_start,
        updated_ts=state_queue.generate_timestamp(),
    )
    with state_queue.sidecar(transaction=True) as session:
        session.run(
            """
            CREATE TRIGGER ignore_driver_claim
            BEFORE UPDATE OF driver_pid, driver_start_time
            ON taut_summon_sessions
            WHEN OLD.member_id = 'm_abc'
            BEGIN
                SELECT RAISE(IGNORE);
            END
            """
        )
    my_pid, my_start = capture_driver_evidence()

    with pytest.raises(DriverConflictError, match="did not acquire"):
        claim_driver(
            state_queue,
            member_id="m_abc",
            driver_pid=my_pid,
            driver_start_time=my_start,
            updated_ts=state_queue.generate_timestamp(),
            takeover=True,
        )

    stored = get_session(state_queue, "m_abc")
    assert stored is not None
    assert (stored["driver_pid"], stored["driver_start_time"]) == (
        dead_pid,
        dead_start,
    )


def test_claim_driver_race_has_exactly_one_owner(summon_db: Path) -> None:
    setup_queue = Queue("taut.summon_state", db_path=str(summon_db))
    children = [
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        for _ in range(2)
    ]
    try:
        ensure_summon_schema(setup_queue)
        record_session(
            setup_queue,
            member_id="m_race",
            token="taut-tok-race",
            provider="claude",
            updated_ts=setup_queue.generate_timestamp(),
        )
        evidence = [capture_driver_evidence(child.pid) for child in children]
        barrier = threading.Barrier(2)

        def race_claim(candidate: tuple[int, str]) -> tuple[int, str] | Exception:
            queue = Queue("taut.summon_state", db_path=str(summon_db))
            try:
                barrier.wait(timeout=5)
                claimed = claim_driver(
                    queue,
                    member_id="m_race",
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
            finally:
                queue.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(race_claim, evidence))

        winners = [outcome for outcome in outcomes if isinstance(outcome, tuple)]
        conflicts = [
            outcome for outcome in outcomes if isinstance(outcome, DriverConflictError)
        ]
        assert len(winners) == 1
        assert len(conflicts) == 1
        assert winners[0] in evidence
        stored = get_session(setup_queue, "m_race")
        assert stored is not None
        assert (stored["driver_pid"], stored["driver_start_time"]) == winners[0]
    finally:
        setup_queue.close()
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()


def test_claim_driver_reclaims_dead_evidence_without_takeover(
    state_queue: Queue,
) -> None:
    # [SUM-11]: driver crash leaves a stale claim that is reclaimable by
    # evidence — a plain restart works without --takeover.
    ensure_summon_schema(state_queue)
    dead_pid, dead_start = _dead_evidence()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        driver_pid=dead_pid,
        driver_start_time=dead_start,
        updated_ts=state_queue.generate_timestamp(),
    )
    my_pid, my_start = capture_driver_evidence()

    row = claim_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
    )

    assert row["driver_pid"] == my_pid


def test_claim_driver_is_idempotent_for_same_evidence(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    my_pid, my_start = capture_driver_evidence()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
    )

    row = claim_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
    )

    assert row["driver_pid"] == my_pid


def test_claim_driver_missing_session_is_an_error(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    my_pid, my_start = capture_driver_evidence()

    with pytest.raises(SummonStateError, match="no summon session"):
        claim_driver(
            state_queue,
            member_id="m_missing",
            driver_pid=my_pid,
            driver_start_time=my_start,
            updated_ts=state_queue.generate_timestamp(),
        )


def test_release_driver_clears_evidence(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    my_pid, my_start = capture_driver_evidence()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
    )

    assert (
        release_driver(
            state_queue,
            member_id="m_abc",
            driver_pid=my_pid,
            driver_start_time=my_start,
            updated_ts=state_queue.generate_timestamp(),
        )
        is True
    )

    row = get_session(state_queue, "m_abc")
    assert row is not None
    assert row["driver_pid"] is None
    assert row["driver_start_time"] is None


def test_release_driver_is_ownership_checked(state_queue: Queue) -> None:
    # A replaced driver's cleanup must never erase its successor's live
    # claim. The no-op returns True because complete different evidence
    # confirms that the caller no longer owns the slot.
    ensure_summon_schema(state_queue)
    my_pid, my_start = capture_driver_evidence()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
    )

    stale_release = release_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=my_pid + 1,
        driver_start_time="not-the-stored-evidence",
        updated_ts=state_queue.generate_timestamp(),
    )

    assert stale_release is True
    row = get_session(state_queue, "m_abc")
    assert row is not None
    assert row["driver_pid"] == my_pid
    assert row["driver_start_time"] == my_start


def test_release_driver_rejects_zero_row_conditional_clear(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    my_pid, my_start = capture_driver_evidence()
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
    )
    with state_queue.sidecar(transaction=True) as session:
        session.run(
            """
            CREATE TRIGGER ignore_driver_release
            BEFORE UPDATE OF driver_pid ON taut_summon_sessions
            WHEN NEW.driver_pid IS NULL
            BEGIN
                SELECT RAISE(IGNORE);
            END
            """
        )

    assert not release_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=my_pid,
        driver_start_time=my_start,
        updated_ts=state_queue.generate_timestamp(),
    )
    row = get_session(state_queue, "m_abc")
    assert row is not None
    assert (row["driver_pid"], row["driver_start_time"]) == (my_pid, my_start)


def test_release_driver_rejects_partial_confirmation(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    record_session(
        state_queue,
        member_id="m_abc",
        token="taut-tok-1",
        provider="claude",
        updated_ts=state_queue.generate_timestamp(),
    )
    with state_queue.sidecar(transaction=True) as session:
        session.run(
            """
            UPDATE taut_summon_sessions
            SET driver_pid = ?, driver_start_time = NULL
            WHERE member_id = ?
            """,
            (1234, "m_abc"),
        )

    assert not release_driver(
        state_queue,
        member_id="m_abc",
        driver_pid=1234,
        driver_start_time="unknown",
        updated_ts=state_queue.generate_timestamp(),
    )


# --- claims table (bootstrap serialization) ---------------------------------


def test_claim_name_refuses_live_claim(
    state_queue: Queue, live_child: subprocess.Popen[bytes]
) -> None:
    ensure_summon_schema(state_queue)
    child_pid, child_start = capture_driver_evidence(live_child.pid)
    claim_name(
        state_queue,
        name="reviewer",
        provider="claude",
        driver_pid=child_pid,
        driver_start_time=child_start,
        claimed_ts=state_queue.generate_timestamp(),
    )
    my_pid, my_start = capture_driver_evidence()

    with pytest.raises(ClaimConflictError, match="live"):
        claim_name(
            state_queue,
            name="reviewer",
            provider="claude",
            driver_pid=my_pid,
            driver_start_time=my_start,
            claimed_ts=state_queue.generate_timestamp(),
        )


def test_claim_name_serializes_display_case_through_one_route_key(
    state_queue: Queue, live_child: subprocess.Popen[bytes]
) -> None:
    ensure_summon_schema(state_queue)
    child_pid, child_start = capture_driver_evidence(live_child.pid)
    stored = claim_name(
        state_queue,
        name="Scripted",
        provider="scripted",
        driver_pid=child_pid,
        driver_start_time=child_start,
        claimed_ts=state_queue.generate_timestamp(),
    )
    my_pid, my_start = capture_driver_evidence()

    with pytest.raises(ClaimConflictError, match="live"):
        claim_name(
            state_queue,
            name="scripted",
            provider="scripted",
            driver_pid=my_pid,
            driver_start_time=my_start,
            claimed_ts=state_queue.generate_timestamp(),
        )

    assert stored["name"] == "scripted"
    assert get_claim(state_queue, name="SCRIPTED", provider="scripted") == stored


def test_claim_name_reclaims_dead_claim(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    dead_pid, dead_start = _dead_evidence()
    claim_name(
        state_queue,
        name="reviewer",
        provider="claude",
        driver_pid=dead_pid,
        driver_start_time=dead_start,
        claimed_ts=state_queue.generate_timestamp(),
    )
    my_pid, my_start = capture_driver_evidence()

    row = claim_name(
        state_queue,
        name="reviewer",
        provider="claude",
        driver_pid=my_pid,
        driver_start_time=my_start,
        claimed_ts=state_queue.generate_timestamp(),
    )

    assert row["driver_pid"] == my_pid


def test_claim_name_distinct_names_do_not_conflict(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    my_pid, my_start = capture_driver_evidence()

    claim_name(
        state_queue,
        name="reviewer",
        provider="claude",
        driver_pid=my_pid,
        driver_start_time=my_start,
        claimed_ts=state_queue.generate_timestamp(),
    )
    claim_name(
        state_queue,
        name="claudette",
        provider="claude",
        driver_pid=my_pid,
        driver_start_time=my_start,
        claimed_ts=state_queue.generate_timestamp(),
    )

    assert get_claim(state_queue, name="reviewer", provider="claude") is not None
    assert get_claim(state_queue, name="claudette", provider="claude") is not None


def test_release_claim_deletes_the_row(state_queue: Queue) -> None:
    ensure_summon_schema(state_queue)
    my_pid, my_start = capture_driver_evidence()
    claim_name(
        state_queue,
        name="reviewer",
        provider="claude",
        driver_pid=my_pid,
        driver_start_time=my_start,
        claimed_ts=state_queue.generate_timestamp(),
    )

    assert (
        release_claim(
            state_queue,
            name="reviewer",
            provider="claude",
            driver_pid=my_pid,
            driver_start_time=my_start,
        )
        is True
    )
    assert get_claim(state_queue, name="reviewer", provider="claude") is None
    assert (
        release_claim(
            state_queue,
            name="reviewer",
            provider="claude",
            driver_pid=my_pid,
            driver_start_time=my_start,
        )
        is False
    )


def test_release_claim_is_ownership_checked(state_queue: Queue) -> None:
    # Same rule as release_driver: stale evidence releases nothing.
    ensure_summon_schema(state_queue)
    my_pid, my_start = capture_driver_evidence()
    claim_name(
        state_queue,
        name="reviewer",
        provider="claude",
        driver_pid=my_pid,
        driver_start_time=my_start,
        claimed_ts=state_queue.generate_timestamp(),
    )

    stale_release = release_claim(
        state_queue,
        name="reviewer",
        provider="claude",
        driver_pid=my_pid + 1,
        driver_start_time="not-the-stored-evidence",
    )

    assert stale_release is False
    assert get_claim(state_queue, name="reviewer", provider="claude") is not None


# --- core-oblivious proof ----------------------------------------------------


def test_core_client_flow_is_oblivious_to_summon_state(summon_db: Path) -> None:
    """A db bearing summon tables and sys.* queues stays fully core-valid.

    The representative core flow (init / join / say / read / whoami) runs
    against a database that already carries the summon ledger, a claim,
    and an unregistered ``sys.*`` control queue — none of which core may
    notice ([SUM-8]; plan invariant "extension-owned state only").
    """

    queue = Queue("taut.summon_state", db_path=str(summon_db))
    try:
        core_version_before = _meta_value(queue, "schema_version")
        ensure_summon_schema(queue)
        ts = queue.generate_timestamp()
        pid, start = capture_driver_evidence()
        claim_name(
            queue,
            name="claude",
            provider="claude",
            driver_pid=pid,
            driver_start_time=start,
            claimed_ts=ts,
        )
        record_session(
            queue,
            member_id="m_summoned",
            token="taut-test-token",
            provider="claude",
            provider_session_id="sess-1",
            driver_pid=pid,
            driver_start_time=start,
            updated_ts=ts,
        )
        control: Queue = Queue("sys.ctl_m_summoned", db_path=str(summon_db))
        try:
            control.write('{"command": "PING", "request_id": "r1"}')
        finally:
            control.close()
    finally:
        queue.close()

    van = TautClient(db_path=summon_db, as_name="van")
    van.join("general")
    claude = TautClient(db_path=summon_db, as_name="claude")
    claude.join("general")
    van.say("general", "hello summoned world")

    texts = [message.text for message in claude.read("general")]
    assert "hello summoned world" in texts
    assert van.whoami().name == "van"

    # Core's schema gate and version key are untouched by the extension.
    verify = Queue("taut.summon_state", db_path=str(summon_db))
    try:
        assert _meta_value(verify, "schema_version") == core_version_before
        assert _meta_value(verify, SUMMON_SCHEMA_VERSION_KEY) == str(
            SUMMON_SCHEMA_VERSION
        )
    finally:
        verify.close()
