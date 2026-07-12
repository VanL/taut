from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from simplebroker import BrokerTarget, Queue
from simplebroker.ext import IntegrityError

import taut.identity as identity
import taut.state._sql as sql_state
from taut._constants import META_QUEUE_NAME
from taut.client import TautClient
from taut.state import (
    PORTABLE_SQL_DIALECT,
    POSTGRES_SQL_DIALECT,
    SQLITE_SQL_DIALECT,
    SqlSidecarTautState,
    dialect_for_taut_target,
)
from taut.state._types import IdentityClaimRow, MembershipRow

pytestmark = pytest.mark.shared


def test_dialect_for_taut_target_preserves_resolved_backend_identity(
    tmp_path: Path,
) -> None:
    sqlite_path = tmp_path / "taut.sqlite3"

    path_dialect = dialect_for_taut_target(str(sqlite_path))
    sqlite_dialect = dialect_for_taut_target(
        BrokerTarget(backend_name="sqlite", target=str(sqlite_path))
    )
    postgres_dialect = dialect_for_taut_target(
        BrokerTarget(backend_name="postgres", target="postgresql://example/taut")
    )

    assert path_dialect == SQLITE_SQL_DIALECT
    assert sqlite_dialect == SQLITE_SQL_DIALECT
    assert postgres_dialect == POSTGRES_SQL_DIALECT
    assert path_dialect != PORTABLE_SQL_DIALECT
    assert sqlite_dialect != PORTABLE_SQL_DIALECT
    assert postgres_dialect != PORTABLE_SQL_DIALECT


def test_dialect_for_taut_target_rejects_unknown_resolved_backend() -> None:
    with pytest.raises(RuntimeError, match="unsupported SQL sidecar backend"):
        dialect_for_taut_target(
            BrokerTarget(backend_name="unknown", target="unknown://example")
        )


def test_update_member_persona_preserves_unknown_meta_keys(
    taut_project: Path,
) -> None:
    """REGRESSION guard: persona updates merge into ``meta``, never clobber it.

    Regression-only: this test passes both before and after the F10
    transactional fix and does not prove the lost-update race is closed —
    that proof is by inspection of ``update_member_persona``'s
    single-transaction read-modify-write shape.  Its job is to pin
    merge-preservation of unknown ``meta`` keys against future rewrites.
    """
    TautClient.init()
    client = TautClient()
    queue = Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
    state = SqlSidecarTautState(
        queue,
        dialect_for_taut_target(client.target),
    )
    try:
        state.ensure_schema()
        member = state.insert_member(
            member_id=identity.random_member_id(),
            display_name="PersonaHolder",
            kind="agent",
            uid=1000,
            host_id="host:test",
            host_label="test-host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token="persona-regression-token",
            meta={},
            created_ts=10,
        )
        member_id = member["member_id"]

        # White-box seeding (labeled): write an unknown key straight into
        # the member's meta JSON via a direct sidecar write, bypassing the
        # persona API entirely.
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_members SET meta = ? WHERE member_id = ?",
                (json.dumps({"custom_flag": "kept"}), member_id),
            )

        updated = state.update_member_persona(member_id, "helper")
        assert updated is not None
        assert updated["meta"]["persona"] == "helper"
        assert updated["meta"]["custom_flag"] == "kept"

        cleared = state.update_member_persona(member_id, None)
        assert cleared is not None
        assert "persona" not in cleared["meta"]
        assert cleared["meta"]["custom_flag"] == "kept"

        assert state.update_member_persona("m_missing", "ghost") is None
    finally:
        queue.close()


@pytest.mark.parametrize(
    ("stored", "detail"),
    [
        ("{broken", "invalid JSON"),
        ("[]", "expected an object"),
    ],
)
def test_member_meta_corruption_fails_with_storage_context(
    taut_project: Path,
    stored: str,
    detail: str,
) -> None:
    TautClient.init()
    client = TautClient()
    queue = Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
    state = SqlSidecarTautState(queue, dialect_for_taut_target(client.target))
    try:
        state.ensure_schema()
        member = state.insert_member(
            member_id=identity.random_member_id(),
            display_name="CorruptMeta",
            kind="agent",
            uid=1000,
            host_id="host:test",
            host_label="test-host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token="corrupt-meta-token",
            meta={},
            created_ts=10,
        )
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_members SET meta = ? WHERE member_id = ?",
                (stored, member["member_id"]),
            )

        with pytest.raises(
            RuntimeError,
            match=rf"taut_members\.meta: {detail}",
        ):
            state.get_member(member["member_id"])
    finally:
        queue.close()


@pytest.mark.parametrize(
    ("stored", "detail"),
    [
        ("{broken", "invalid JSON"),
        ("[]", "expected an object"),
    ],
)
def test_thread_meta_corruption_fails_with_storage_context(
    taut_project: Path,
    stored: str,
    detail: str,
) -> None:
    TautClient.init()
    client = TautClient()
    queue = Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
    state = SqlSidecarTautState(queue, dialect_for_taut_target(client.target))
    try:
        state.ensure_schema()
        state.upsert_thread(
            name="general",
            kind="channel",
            parent=None,
            origin_ts=None,
            created_by="m_test",
            meta={},
            created_ts=10,
        )
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_threads SET meta = ? WHERE name = ?",
                (stored, "general"),
            )

        with pytest.raises(
            RuntimeError,
            match=rf"taut_threads\.meta: {detail}",
        ):
            state.get_thread("general")
    finally:
        queue.close()


def test_nullable_owned_metadata_decodes_sql_null_as_empty_object(
    taut_project: Path,
) -> None:
    TautClient.init()
    client = TautClient()
    queue = Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
    state = SqlSidecarTautState(queue, dialect_for_taut_target(client.target))
    try:
        state.ensure_schema()
        member = state.insert_member(
            member_id=identity.random_member_id(),
            display_name="NullableMeta",
            kind="agent",
            uid=1000,
            host_id="host:test",
            host_label="test-host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token="nullable-meta-token",
            meta={},
            created_ts=10,
        )
        state.upsert_thread(
            name="general",
            kind="channel",
            parent=None,
            origin_ts=None,
            created_by=member["member_id"],
            meta={},
            created_ts=20,
        )
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_members SET meta = NULL WHERE member_id = ?",
                (member["member_id"],),
            )
            session.run(
                "UPDATE taut_threads SET meta = NULL WHERE name = ?",
                ("general",),
            )

        decoded_member = state.get_member(member["member_id"])
        decoded_thread = state.get_thread("general")
        assert decoded_member is not None
        assert decoded_thread is not None
        assert decoded_member["meta"] == {}
        assert decoded_thread["meta"] == {}
    finally:
        queue.close()


@pytest.mark.parametrize(
    ("stored", "detail"),
    [
        ("{broken", "invalid JSON"),
        ("[]", "expected an object"),
    ],
)
def test_identity_claim_evidence_corruption_fails_with_storage_context(
    taut_project: Path,
    stored: str,
    detail: str,
) -> None:
    TautClient.init()
    client = TautClient()
    queue = Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
    state = SqlSidecarTautState(queue, dialect_for_taut_target(client.target))
    claim_hash = "ic_" + "e" * 52
    try:
        state.ensure_schema()
        member = state.insert_member(
            member_id=identity.random_member_id(),
            display_name="ClaimHolder",
            kind="agent",
            uid=1000,
            host_id="host:test",
            host_label="test-host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token="corrupt-claim-token",
            meta={},
            created_ts=10,
        )
        state.add_identity_claim(
            claim_hash=claim_hash,
            member_id=member["member_id"],
            claim_kind="agent_process",
            host_id="host:test",
            host_label="test-host",
            evidence={"claim_kind": "agent_process"},
            seen_ts=20,
        )
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_identity_claims SET evidence_json = ? "
                "WHERE claim_hash = ?",
                (stored, claim_hash),
            )

        with pytest.raises(
            RuntimeError,
            match=rf"taut_identity_claims\.evidence_json: {detail}",
        ):
            state.get_identity_claim(claim_hash)
    finally:
        queue.close()


@pytest.mark.parametrize(
    ("stored", "detail"),
    [
        ("{broken", "invalid JSON"),
        ('{"old":"general","new":"ops"}', "expected a list"),
        ('["general"]', "item 0: expected an object"),
        ('[{"old":"general"}]', "item 0: expected string old and new"),
        ('[{"old":1,"new":"ops"}]', "item 0: expected string old and new"),
    ],
)
def test_channel_rename_corruption_fails_without_completing_marker(
    taut_project: Path,
    stored: str,
    detail: str,
) -> None:
    TautClient.init()
    client = TautClient()
    queue = Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
    state = SqlSidecarTautState(queue, dialect_for_taut_target(client.target))
    try:
        state.ensure_schema()
        state.start_channel_rename(
            old_name="general",
            new_name="ops",
            affected=[{"old": "general", "new": "ops"}],
            started_ts=10,
        )
        with queue.sidecar(transaction=True) as session:
            session.run(
                "UPDATE taut_channel_renames SET affected_json = ? WHERE old_name = ?",
                (stored, "general"),
            )

        with pytest.raises(
            RuntimeError,
            match=rf"taut_channel_renames\.affected_json: {detail}",
        ):
            state.incomplete_channel_renames()

        with queue.sidecar() as session:
            rows = list(
                session.run(
                    "SELECT state FROM taut_channel_renames WHERE old_name = ?",
                    ("general",),
                    fetch=True,
                )
            )
        assert rows == [("started",)]
    finally:
        queue.close()


def test_add_identity_claim_insert_race_is_idempotent(
    taut_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    TautClient.init()
    client = TautClient()
    queue = Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
    state = SqlSidecarTautState(
        queue,
        dialect_for_taut_target(client.target),
    )
    claim_hash = "ic_" + "r" * 52
    original_get_identity_claim = sql_state.get_identity_claim
    stale_reads = 1
    try:
        state.ensure_schema()
        member = state.insert_member(
            member_id=identity.random_member_id(),
            display_name="RaceHolder",
            kind="agent",
            uid=1000,
            host_id="host:test",
            host_label="test-host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token="contract-token-race-holder",
            meta={},
            created_ts=10,
        )
        state.add_identity_claim(
            claim_hash=claim_hash,
            member_id=member["member_id"],
            claim_kind="agent_process",
            host_id="host:test",
            host_label="test-host",
            evidence={"claim_kind": "agent_process", "host_id": "host:test"},
            seen_ts=20,
        )

        def racing_get_identity_claim(
            claim_queue: Queue, wanted: str
        ) -> IdentityClaimRow | None:
            nonlocal stale_reads
            if wanted == claim_hash and stale_reads:
                stale_reads -= 1
                return None
            return original_get_identity_claim(claim_queue, wanted)

        monkeypatch.setattr(sql_state, "get_identity_claim", racing_get_identity_claim)

        raced = state.add_identity_claim(
            claim_hash=claim_hash,
            member_id=member["member_id"],
            claim_kind="agent_process",
            host_id="host:test",
            host_label="test-host",
            evidence={"claim_kind": "agent_process", "host_id": "host:test"},
            seen_ts=30,
        )

        assert raced["member_id"] == member["member_id"]
        assert raced["last_seen_ts"] == 30
    finally:
        queue.close()


def test_state_contract_preserves_identity_membership_cursor_and_rename(
    taut_project: Path,
) -> None:
    TautClient.init()
    client = TautClient()
    queue = Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
    state = SqlSidecarTautState(
        queue,
        dialect_for_taut_target(client.target),
    )

    try:
        state.ensure_schema()
        assert state.get_schema_version() == 2

        member = state.insert_member(
            member_id=identity.random_member_id(),
            display_name="VanL",
            kind="human",
            uid=1000,
            host_id="host:test",
            host_label="test-host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token="contract-token-van",
            meta={},
            created_ts=10,
        )
        other = state.insert_member(
            member_id=identity.random_member_id(),
            display_name="Other",
            kind="human",
            uid=1001,
            host_id="host:test",
            host_label="test-host",
            anchor_pid=None,
            anchor_start_time=None,
            fingerprint=None,
            token="contract-token-other",
            meta={},
            created_ts=11,
        )

        with pytest.raises(IntegrityError):
            state.add_member_alias(
                member_id=other["member_id"],
                alias="vanl",
                created_ts=12,
            )

        state.add_identity_claim(
            claim_hash="ic_" + "c" * 52,
            member_id=member["member_id"],
            claim_kind="human_session",
            host_id="host:test",
            host_label="test-host",
            evidence={"claim_kind": "human_session", "host_id": "host:test"},
            seen_ts=20,
        )
        resolved = state.get_member_by_claim_hash("ic_" + "c" * 52)
        assert resolved is not None
        assert resolved["member_id"] == member["member_id"]

        by_route = state.get_member_by_route_key("vanl")
        assert by_route is not None
        assert by_route["member_id"] == member["member_id"]

        renamed_member = state.update_member_name(member["member_id"], "Renamed")
        assert renamed_member["display_name"] == "Renamed"
        moved = state.get_member_by_route_key("renamed")
        assert moved is not None
        assert moved["member_id"] == member["member_id"]
        assert state.get_member_by_route_key("vanl") is None

        state.upsert_thread(
            name="general",
            kind="channel",
            parent=None,
            origin_ts=None,
            created_by=member["member_id"],
            meta={},
            created_ts=30,
        )
        state.upsert_thread(
            name="general.31",
            kind="subthread",
            parent="general",
            origin_ts=31,
            created_by=member["member_id"],
            meta={},
            created_ts=31,
        )
        state.add_membership(
            thread="general",
            member_id=member["member_id"],
            joined_ts=30,
            last_seen_ts=100,
        )
        state.advance_cursor(
            thread="general",
            member_id=member["member_id"],
            seen_ts=90,
        )
        state.advance_cursor(
            thread="general",
            member_id=member["member_id"],
            seen_ts=110,
        )
        membership = state.get_membership(
            thread="general",
            member_id=member["member_id"],
        )
        assert membership is not None
        assert membership["last_seen_ts"] == 110

        affected = [
            {"old": "general", "new": "ops"},
            {"old": "general.31", "new": "ops.31"},
        ]
        state.start_channel_rename(
            old_name="general",
            new_name="ops",
            affected=affected,
            started_ts=120,
        )
        assert state.incomplete_channel_renames()[0]["old_name"] == "general"
        state.apply_channel_rename_state(
            old_name="general",
            new_name="ops",
            affected=affected,
            updated_ts=130,
        )

        assert state.get_thread("general") is None
        renamed = state.get_thread("ops")
        assert renamed is not None
        assert renamed["name"] == "ops"
        assert state.incomplete_channel_renames() == []
    finally:
        queue.close()


def test_concurrent_membership_removal_reports_exactly_one_winner(
    taut_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TautClient.init()
    client = TautClient()
    setup_queue = Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
    setup_state = SqlSidecarTautState(
        setup_queue, dialect_for_taut_target(client.target)
    )
    member_id = identity.random_member_id()
    setup_state.ensure_schema()
    setup_state.insert_member(
        member_id=member_id,
        display_name="LeavingMember",
        kind="agent",
        uid=1000,
        host_id="host:test",
        host_label="test-host",
        anchor_pid=None,
        anchor_start_time=None,
        fingerprint=None,
        token="membership-remove-race-token",
        meta={},
        created_ts=10,
    )
    setup_state.add_membership(
        thread="general",
        member_id=member_id,
        joined_ts=20,
        last_seen_ts=20,
    )
    queues = [
        Queue(META_QUEUE_NAME, db_path=client.target, config=client.config)
        for _ in range(2)
    ]
    states = [
        SqlSidecarTautState(queue, dialect_for_taut_target(client.target))
        for queue in queues
    ]
    start = threading.Barrier(2)
    stale_read = threading.Barrier(2)
    original_get_membership = sql_state.get_membership

    def synchronized_get_membership(
        queue: Queue, *, thread: str, member_id: str
    ) -> MembershipRow | None:
        row = original_get_membership(queue, thread=thread, member_id=member_id)
        stale_read.wait(timeout=5)
        return row

    monkeypatch.setattr(sql_state, "get_membership", synchronized_get_membership)

    def remove(index: int) -> bool:
        start.wait(timeout=5)
        return states[index].remove_membership(thread="general", member_id=member_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(remove, range(2)))

        assert sorted(outcomes) == [False, True]
        assert (
            original_get_membership(setup_queue, thread="general", member_id=member_id)
            is None
        )
    finally:
        setup_queue.close()
        for queue in queues:
            queue.close()
