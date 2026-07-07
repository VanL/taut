from __future__ import annotations

import json
from pathlib import Path

import pytest
from simplebroker import BrokerTarget, Queue
from simplebroker.ext import IntegrityError

import taut.identity as identity
from taut._constants import META_QUEUE_NAME
from taut.client import TautClient
from taut.state import (
    PORTABLE_SQL_DIALECT,
    POSTGRES_SQL_DIALECT,
    SQLITE_SQL_DIALECT,
    SqlSidecarTautState,
    dialect_for_taut_target,
)

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
